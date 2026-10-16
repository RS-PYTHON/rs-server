# Copyright 2023-2026 Airbus, CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Search of catalog items by `externalIds`.

Items carry `properties.externalIds` as a list of `{"scheme": ..., "value": ...}`
objects. pgstac >= 0.10 cannot search inside such a list with CQL2: queryables
only accept a JSON key path, and the array operators compare whole elements.

The catalog therefore resolves the `externalIds` conditions of a search itself,
with a jsonb containment query (`@>`) served by a GIN index (SQL_CREATE_EXTERNAL_IDS_INDEXES),
and replaces each condition by the `collection`/`id` of the matching items
before forwarding the search to pgstac.

Only the searches that this index serves efficiently are accepted:
`scheme:value` and `value` (without scheme). A search by scheme only, or
matching more than EXTERNAL_IDS_MAX_MATCHES items, is refused.
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from rs_server_common.utils.logging import Logging
from starlette.status import HTTP_400_BAD_REQUEST

logger = Logging.default(__name__)

EXTERNAL_IDS_PROPERTY = "externalIds"

# Maximum number of items that one externalIds condition may match.
EXTERNAL_IDS_MAX_MATCHES = 1000

# CQL2 operators accepted on externalIds: those meaning "any of these ids" and "all of these ids".
ANY_OPERATORS = ("=", "eq", "in", "a_overlaps")
ALL_OPERATORS = ("a_contains",)
BOOLEAN_OPERATORS = ("and", "or", "not")

# The index is created on pgstac.items, so that PostgreSQL creates it on every (future) partition,
# and on pgstac.queryable_index_template, so that pgstac sees it as one of the indexes of items
# and never drops it as an orphan (pgstac.maintain_partitions(dropindexes => true)).
# It is created at deployment time, as the other pgstac customizations: keep this SQL aligned with
# rs-server-deployment (apps/01-cloudnative-pgstac) and rs-demo (local-mode/scripts/pgstac_post_actions.py).
SQL_CREATE_EXTERNAL_IDS_INDEXES = [
    """CREATE INDEX IF NOT EXISTS items_external_ids_idx ON pgstac.items
        USING GIN ((content->'properties'->'externalIds') jsonb_path_ops)""",
    """CREATE INDEX IF NOT EXISTS queryable_index_template_external_ids_idx ON pgstac.queryable_index_template
        USING GIN ((content->'properties'->'externalIds') jsonb_path_ops)""",
]

# Must use the exact indexed expression to be served by the index.
SQL_FIND_ITEMS = """
    SELECT collection, id FROM pgstac.items
    WHERE content->'properties'->'externalIds' @> $1::text::jsonb
    {collections_clause}
    LIMIT $2
"""

# A list of {"scheme": ..., "value": ...} or {"value": ...} objects that an item externalIds must contain.
Terms = list[dict[str, str]]
# Returns the (collection, id) of the items matching the terms, all of them or any of them.
ItemsLookup = Callable[[Terms, bool], Awaitable[set[tuple[str, str]]]]


def bad_request(detail: str) -> HTTPException:
    """Return the HTTP 400 error raised for an externalIds search that is not supported."""
    return HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=detail)


def parse_external_ids(raw: Any) -> Terms:
    """
    Parse the externalIds searched by a client.

    Accepted forms are `scheme:value`, `:value` and `value`, as a string, a
    comma-separated string or a list of them. The scheme is everything before the
    first colon, so a value containing colons without scheme is written `:value`.

    Args:
        raw: the searched externalIds.

    Returns:
        Terms: the distinct terms, in order of appearance.

    Raises:
        HTTPException: 400 if there is no term, or a term has no value (e.g. a search by scheme only)
            or is not a string.
    """
    terms: Terms = []
    for item in raw if isinstance(raw, list) else [raw]:
        if not isinstance(item, str):
            raise bad_request(f"Invalid externalIds value {item!r}: a string is expected.")
        for part in item.split(","):
            if not part.strip():
                continue
            scheme, colon, value = part.partition(":")
            scheme, value = (scheme.strip(), value.strip()) if colon else ("", scheme.strip())
            if not value:
                raise bad_request(
                    f"Invalid externalIds value {part.strip()!r}: an identifier is required "
                    "('scheme:value' or 'value'), searching by scheme only is not supported.",
                )
            term = {"scheme": scheme, "value": value} if scheme else {"value": value}
            if term not in terms:
                terms.append(term)
    if not terms:
        raise bad_request("No externalIds identifier to search.")
    return terms


def has_external_ids(node: Any) -> bool:
    """Check whether a CQL2-JSON filter references the externalIds property."""
    if isinstance(node, dict):
        return node.get("property") == EXTERNAL_IDS_PROPERTY or any(has_external_ids(v) for v in node.values())
    if isinstance(node, list):
        return any(has_external_ids(v) for v in node)
    return False


def matching_items_filter(items: set[tuple[str, str]]) -> dict:
    """Return the CQL2-JSON filter selecting the given (collection, id) items."""
    if not items:
        # Always false: an item id is never null.
        return {"op": "isNull", "args": [{"property": "id"}]}
    filters = []
    for collection in sorted({collection for collection, _ in items}):
        ids = sorted(item_id for item_collection, item_id in items if item_collection == collection)
        filters.append(
            {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "collection"}, collection]},
                    {"op": "in", "args": [{"property": "id"}, ids]},
                ],
            },
        )
    return filters[0] if len(filters) == 1 else {"op": "or", "args": filters}


async def resolve_external_ids_filter(node: Any, lookup: ItemsLookup) -> Any:
    """
    Replace the externalIds conditions of a CQL2-JSON filter by the items they match.

    Supported conditions are `=`, `in` and `a_overlaps` (any of the ids) and
    `a_contains` (all of the ids), in any argument order, inside any and/or/not.

    Args:
        node: the CQL2-JSON filter.
        lookup: function returning the items matching externalIds terms.

    Returns:
        The filter, without any reference to externalIds.

    Raises:
        HTTPException: 400 if an externalIds condition is not supported.
    """
    if not has_external_ids(node):
        return node
    op = str(node.get("op", "")).lower() if isinstance(node, dict) else ""
    args = node.get("args") if isinstance(node, dict) else None
    if op in BOOLEAN_OPERATORS and isinstance(args, list):
        return {**node, "args": [await resolve_external_ids_filter(arg, lookup) for arg in args]}
    if op in ANY_OPERATORS + ALL_OPERATORS and isinstance(args, list) and len(args) == 2:
        for prop, values in (args, args[::-1]):
            if prop == {"property": EXTERNAL_IDS_PROPERTY} and not has_external_ids(values):
                terms = parse_external_ids(values)
                return matching_items_filter(await lookup(terms, op in ALL_OPERATORS))
    raise bad_request(
        f"Unsupported externalIds filter {json.dumps(node)}: externalIds can only be searched with "
        "'=', 'in', 'a_overlaps' or 'a_contains' and identifiers ('scheme:value' or 'value').",
    )


def items_lookup(pool, collections: list[str] | None) -> ItemsLookup:
    """
    Return the function finding the items by externalIds in the database.

    Args:
        pool: asyncpg connection pool to pgstac.
        collections: pgstac ids of the searched collections, None or empty for all of them.
    """
    collections_clause = "AND collection = ANY($3::text[])" if collections else ""
    sql = SQL_FIND_ITEMS.format(collections_clause=collections_clause)

    async def lookup(terms: Terms, match_all: bool) -> set[tuple[str, str]]:
        # Each @> query is served by the index: "all" is one containment of all the terms,
        # "any" is the union of the containment of each term.
        queries = [terms] if match_all else [[term] for term in terms]
        items: set[tuple[str, str]] = set()
        async with pool.acquire() as conn:
            for query in queries:
                params: list[Any] = [json.dumps(query), EXTERNAL_IDS_MAX_MATCHES + 1]
                if collections:
                    params.append(collections)
                items.update((row["collection"], row["id"]) for row in await conn.fetch(sql, *params))
                if len(items) > EXTERNAL_IDS_MAX_MATCHES:
                    raise bad_request(
                        f"More than {EXTERNAL_IDS_MAX_MATCHES} items match externalIds {terms}, "
                        "please search more precise identifiers.",
                    )
        logger.debug("Items matching externalIds %s (all=%s): %s", terms, match_all, items)
        return items

    return lookup
