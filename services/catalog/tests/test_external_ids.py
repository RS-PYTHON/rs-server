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

"""Unit tests of the resolution of the externalIds conditions of a catalog search."""

import pytest
from fastapi import HTTPException
from rs_server_catalog.data_management.external_ids import (
    has_external_ids,
    matching_items_filter,
    parse_external_ids,
    resolve_external_ids_filter,
)

PROP = {"property": "externalIds"}
NO_ITEM = {"op": "isNull", "args": [{"property": "id"}]}


def items_filter(collection: str, *ids: str) -> dict:
    """Return the filter expected for items of one collection."""
    return {
        "op": "and",
        "args": [
            {"op": "=", "args": [{"property": "collection"}, collection]},
            {"op": "in", "args": [{"property": "id"}, list(ids)]},
        ],
    }


class FakeLookup:
    """Record the lookups and return one item named after the terms."""

    def __init__(self):
        self.calls: list[tuple[list[dict], bool]] = []

    async def __call__(self, terms: list[dict], match_all: bool) -> set[tuple[str, str]]:
        self.calls.append((terms, match_all))
        return {("col", "-".join(term["value"] for term in terms))}


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param("prip:U1", [{"scheme": "prip", "value": "U1"}], id="scheme-and-value"),
        pytest.param("U1", [{"value": "U1"}], id="value"),
        pytest.param(":U1", [{"value": "U1"}], id="empty-scheme"),
        pytest.param(" prip : U1 ", [{"scheme": "prip", "value": "U1"}], id="surrounding-spaces"),
        pytest.param(":urn:uuid:U1", [{"value": "urn:uuid:U1"}], id="value-with-colons"),
        pytest.param("urn:uuid:U1", [{"scheme": "urn", "value": "uuid:U1"}], id="scheme-before-first-colon"),
        pytest.param(
            "prip:U1,U2, ,prip:U1,",
            [{"scheme": "prip", "value": "U1"}, {"value": "U2"}],
            id="comma-separated-deduplicated",
        ),
        pytest.param(
            ["prip:U1", "auxip:U2,U3"],
            [{"scheme": "prip", "value": "U1"}, {"scheme": "auxip", "value": "U2"}, {"value": "U3"}],
            id="list",
        ),
    ],
)
def test_parse_external_ids(raw, expected):
    """Searched identifiers are scheme:value, :value or value, in strings, comma-separated strings or lists."""
    assert parse_external_ids(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("auxip:", id="scheme-only"),
        pytest.param("prip:U1,auxip:", id="scheme-only-among-others"),
        pytest.param(":", id="colon-only"),
        pytest.param("", id="empty"),
        pytest.param(" , ", id="blank"),
        pytest.param([], id="empty-list"),
        pytest.param(None, id="null"),
        pytest.param(42, id="number"),
        pytest.param(["prip:U1", {"scheme": "prip"}], id="object"),
    ],
)
def test_parse_external_ids_refuses(raw):
    """A search without identifier, by scheme only, or with a value that is not a string is refused."""
    with pytest.raises(HTTPException) as error:
        parse_external_ids(raw)
    assert error.value.status_code == 400


@pytest.mark.parametrize(
    "node, expected",
    [
        ({"op": "=", "args": [PROP, "U1"]}, True),
        ({"op": "not", "args": [{"op": "and", "args": [{"op": "=", "args": [PROP, "U1"]}]}]}, True),
        ({"op": "=", "args": [{"property": "owner"}, "externalIds"]}, False),
        (None, False),
    ],
)
def test_has_external_ids(node, expected):
    """Only a reference to the externalIds property counts, at any depth."""
    assert has_external_ids(node) is expected


def test_matching_items_filter_without_items():
    """No matching item gives an always false filter."""
    assert matching_items_filter(set()) == NO_ITEM


def test_matching_items_filter_by_collection():
    """Items are selected by collection, since item ids are only unique in a collection."""
    assert matching_items_filter({("b", "i2"), ("a", "i3"), ("b", "i1")}) == {
        "op": "or",
        "args": [items_filter("a", "i3"), items_filter("b", "i1", "i2")],
    }
    assert matching_items_filter({("a", "i1")}) == items_filter("a", "i1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node, expected_calls",
    [
        pytest.param({"op": "=", "args": [PROP, "prip:U1"]}, [([{"scheme": "prip", "value": "U1"}], False)], id="eq"),
        pytest.param({"op": "eq", "args": ["U1", PROP]}, [([{"value": "U1"}], False)], id="eq-value-first"),
        pytest.param(
            {"op": "in", "args": [PROP, ["prip:U1", "U2"]]},
            [([{"scheme": "prip", "value": "U1"}, {"value": "U2"}], False)],
            id="in",
        ),
        pytest.param({"op": "A_OVERLAPS", "args": [PROP, ["U1"]]}, [([{"value": "U1"}], False)], id="a_overlaps"),
        pytest.param(
            {"op": "a_contains", "args": [PROP, ["prip:U1", "U2"]]},
            [([{"scheme": "prip", "value": "U1"}, {"value": "U2"}], True)],
            id="a_contains",
        ),
    ],
)
async def test_resolve_external_ids_condition(node, expected_calls):
    """Each supported condition is replaced by the items found by one lookup of all or any of its ids."""
    lookup = FakeLookup()
    resolved = await resolve_external_ids_filter(node, lookup)
    assert lookup.calls == expected_calls
    assert resolved == items_filter("col", "-".join(term["value"] for term in expected_calls[0][0]))


@pytest.mark.asyncio
async def test_resolve_external_ids_in_boolean_filter():
    """Conditions are resolved inside and/or/not, the rest of the filter is kept."""
    other = {"op": "=", "args": [{"property": "width"}, 2500]}
    node = {
        "op": "or",
        "args": [
            {"op": "and", "args": [other, {"op": "=", "args": [PROP, "U1"]}]},
            {"op": "not", "args": [{"op": "=", "args": [PROP, "U2"]}]},
        ],
    }
    assert await resolve_external_ids_filter(node, FakeLookup()) == {
        "op": "or",
        "args": [
            {"op": "and", "args": [other, items_filter("col", "U1")]},
            {"op": "not", "args": [items_filter("col", "U2")]},
        ],
    }


@pytest.mark.asyncio
async def test_resolve_filter_without_external_ids():
    """A filter without externalIds is not changed and no lookup is done."""
    lookup = FakeLookup()
    node = {"op": "=", "args": [{"property": "width"}, 2500]}
    assert await resolve_external_ids_filter(node, lookup) == node
    assert not lookup.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node",
    [
        pytest.param({"op": "=", "args": [PROP, "auxip:"]}, id="scheme-only"),
        pytest.param({"op": "like", "args": [PROP, "%U1%"]}, id="like"),
        pytest.param({"op": "<>", "args": [PROP, "U1"]}, id="not-equal"),
        pytest.param({"op": "isNull", "args": [PROP]}, id="is-null"),
        pytest.param({"op": "a_equals", "args": [PROP, ["U1"]]}, id="a_equals"),
        pytest.param({"op": "a_contained_by", "args": [PROP, ["U1"]]}, id="a_contained_by"),
        pytest.param({"op": "=", "args": [PROP, PROP]}, id="property-compared-to-itself"),
        pytest.param({"op": "=", "args": [PROP, {"property": "id"}]}, id="property-compared-to-property"),
        pytest.param({"op": "=", "args": [PROP, 42]}, id="number"),
        pytest.param({"op": "in", "args": [PROP, ["U1"], "U2"]}, id="three-arguments"),
        pytest.param({"op": "and", "args": [{"op": "upper", "args": [PROP]}]}, id="function"),
    ],
)
async def test_resolve_external_ids_refuses(node):
    """Any other use of externalIds is refused rather than giving a slow or wrong search."""
    lookup = FakeLookup()
    with pytest.raises(HTTPException) as error:
        await resolve_external_ids_filter(node, lookup)
    assert error.value.status_code == 400
    assert not lookup.calls
