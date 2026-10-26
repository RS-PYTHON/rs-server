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
objects, possibly with other fields. A searched identifier is:

- `scheme:value`: an external identifier of the item has this scheme and this value,
- `value` or `:value`: an external identifier of the item has this value, whatever its scheme,
- `scheme:`: an external identifier of the item has this scheme, whatever its value.

Why a custom CQL2 operator:
    pgstac >= 0.10 cannot search inside a list of objects with the standard CQL2
    operators: queryables only accept a JSON key path, and the array operators
    (`a_overlaps`...) compare whole elements. But each of the searches above is a
    jsonb containment, e.g. `externalIds @> '[{"scheme": "prip"}]'`, that a GIN
    index serves efficiently.

    pgstac translates the CQL2 operators that it doesn't know with the SQL templates
    of its `pgstac.cql2_ops` table. The catalog database therefore registers
    there the `external_ids_contains` operator (SQL_CREATE_EXTERNAL_IDS_OPERATOR),
    whose template is exactly the expression of the GIN index
    (SQL_CREATE_EXTERNAL_IDS_INDEXES), so that PostgreSQL uses the index:

        {"op": "external_ids_contains", "args": ["[{\"scheme\": \"prip\", \"value\": \"U1\"}]"]}
        -> (content->'properties'->'externalIds' @> '[{"scheme": "prip", "value": "U1"}]'::jsonb)

    The argument is the JSON of the terms as a string, so that the filter is valid
    CQL2 (stac-fastapi-pgstac validates it with cql2). It is a literal, quoted by
    pgstac (no SQL injection), and a constant for PostgreSQL.

What the catalog does:
    Before forwarding a search to pgstac, the catalog replaces the `externalIds`
    search parameter and the `externalIds` conditions of the CQL2 filter by this
    operator (see `translate_external_ids_filter`). pgstac then evaluates the
    whole search: the SQL query has the size of the search, not of the number of
    matching items, and the pagination works as for any other search.

    Searching items with any of several identifiers (the parameter, `=`, `in`,
    `a_overlaps`) gives one operator per identifier, combined with `or`; searching
    items with all of them (`a_contains`) gives one operator with all of them.
    Other uses of externalIds, which the index cannot serve, are refused (HTTP 400).

    As for any property, an item without externalIds never matches a condition on
    them, even negated: `NOT (externalIds = 'U1')` only finds the items that have
    externalIds, none of them being `U1`.

Deployment:
    The operator and the indexes are created at deployment time, as the other
    pgstac customizations: keep this SQL aligned with rs-server-deployment
    (apps/01-cloudnative-pgstac) and rs-demo (local-mode/scripts/pgstac_post_actions.py).
"""

import json
from typing import Any

from fastapi import HTTPException
from starlette.status import HTTP_400_BAD_REQUEST

EXTERNAL_IDS_PROPERTY = "externalIds"

# CQL2 operator registered in pgstac.cql2_ops: the externalIds of an item contain all the given terms.
EXTERNAL_IDS_OPERATOR = "external_ids_contains"

# CQL2 operators accepted on externalIds: those meaning "any of these ids" and "all of these ids".
ANY_OPERATORS = ("=", "eq", "in", "a_overlaps")
ALL_OPERATORS = ("a_contains",)
BOOLEAN_OPERATORS = ("and", "or", "not")

# The operator is EXTERNAL_IDS_OPERATOR, written as a literal so that this SQL is a constant.
# The template must be exactly the expression of the indexes, so that PostgreSQL uses them.
# Running it again (at each deployment) restores the operator if a pgstac migration removed it.
SQL_CREATE_EXTERNAL_IDS_OPERATOR = """
    INSERT INTO pgstac.cql2_ops (op, template)
    VALUES ('external_ids_contains', '(content->''properties''->''externalIds'' @> %s::jsonb)')
    ON CONFLICT (op) DO UPDATE SET template = EXCLUDED.template
"""

# The index is created on pgstac.items, so that PostgreSQL creates it on every (future) partition,
# and on pgstac.queryable_index_template, so that pgstac sees it as one of the indexes of items
# and never drops it as an orphan (pgstac.maintain_partitions(dropindexes => true)).
SQL_CREATE_EXTERNAL_IDS_INDEXES = [
    """CREATE INDEX IF NOT EXISTS items_external_ids_idx ON pgstac.items
        USING GIN ((content->'properties'->'externalIds') jsonb_path_ops)""",
    """CREATE INDEX IF NOT EXISTS queryable_index_template_external_ids_idx ON pgstac.queryable_index_template
        USING GIN ((content->'properties'->'externalIds') jsonb_path_ops)""",
]

# A list of {"scheme": ..., "value": ...}, {"value": ...} or {"scheme": ...} objects
# that the externalIds of an item must contain.
Terms = list[dict[str, str]]


def bad_request(detail: str) -> HTTPException:
    """Return the HTTP 400 error raised for an externalIds search that is not supported."""
    return HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=detail)


def parse_external_ids(raw: Any) -> Terms:
    """
    Parse the externalIds searched by a client.

    Accepted forms are `scheme:value`, `:value` and `value` (only the value must
    match) and `scheme:` (only the scheme must match), as a string, a
    comma-separated string or a list of them. The scheme is everything before the
    first colon, so a value containing colons without scheme is written `:value`.

    Args:
        raw: the searched externalIds.

    Returns:
        Terms: the distinct terms, in order of appearance.

    Raises:
        HTTPException: 400 if there is no term, or a term has neither scheme nor value
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
            if not scheme and not value:
                raise bad_request(
                    f"Invalid externalIds value {part.strip()!r}: a scheme or a value is required "
                    "('scheme:value', 'value' or 'scheme:').",
                )
            term = {key: text for key, text in (("scheme", scheme), ("value", value)) if text}
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


def external_ids_contains(terms: Terms) -> dict:
    """
    Return the CQL2-JSON condition selecting the items whose externalIds contain all the terms.

    The terms are given as a JSON string: a list of objects is not a CQL2 expression, so
    stac-fastapi-pgstac (>= 7.2.0) would reject the filter when validating it with cql2.
    """
    return {"op": EXTERNAL_IDS_OPERATOR, "args": [json.dumps(terms)]}


def translate_external_ids_filter(node: Any) -> Any:
    """
    Replace the externalIds conditions of a CQL2-JSON filter by the `external_ids_contains` operator.

    Supported conditions are `=`, `in` and `a_overlaps` (any of the ids) and
    `a_contains` (all of the ids), in any argument order, inside any and/or/not.

    Args:
        node: the CQL2-JSON filter.

    Returns:
        The filter, without any reference to the externalIds property.

    Raises:
        HTTPException: 400 if an externalIds condition is not supported.
    """
    if not has_external_ids(node):
        return node
    op = str(node.get("op", "")).lower() if isinstance(node, dict) else ""
    args = node.get("args") if isinstance(node, dict) else None
    if op in BOOLEAN_OPERATORS and isinstance(args, list):
        return {**node, "args": [translate_external_ids_filter(arg) for arg in args]}
    if op in ANY_OPERATORS + ALL_OPERATORS and isinstance(args, list) and len(args) == 2:
        for prop, values in (args, args[::-1]):
            if prop == {"property": EXTERNAL_IDS_PROPERTY} and not has_external_ids(values):
                terms = parse_external_ids(values)
                if op in ALL_OPERATORS:
                    return external_ids_contains(terms)
                conditions = [external_ids_contains([term]) for term in terms]
                return conditions[0] if len(conditions) == 1 else {"op": "or", "args": conditions}
    raise bad_request(
        f"Unsupported externalIds filter {json.dumps(node)}: externalIds can only be searched with "
        "'=', 'in', 'a_overlaps' or 'a_contains' and identifiers ('scheme:value', 'value' or 'scheme:').",
    )
