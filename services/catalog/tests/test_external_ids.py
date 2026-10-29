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

"""Unit tests of the translation of the externalIds conditions of a catalog search."""

import json

import cql2
import pytest
from fastapi import HTTPException
from rs_server_catalog.data_management.external_ids import (
    has_external_ids,
    parse_external_ids,
    translate_external_ids_filter,
)
from rs_server_catalog.middleware.request_manager import translate_external_ids_search

PROP = {"property": "externalIds"}
OTHER = {"op": "=", "args": [{"property": "width"}, 2500]}


def contains(*terms: dict) -> dict:
    """Return the condition expected for externalIds containing all the terms."""
    return {"op": "external_ids_contains", "args": [json.dumps(list(terms))]}


@pytest.mark.parametrize(
    "raw, expected",
    [
        pytest.param("prip:U1", [{"scheme": "prip", "value": "U1"}], id="scheme-and-value"),
        pytest.param("U1", [{"value": "U1"}], id="value"),
        pytest.param(":U1", [{"value": "U1"}], id="empty-scheme"),
        pytest.param(" prip : U1 ", [{"scheme": "prip", "value": "U1"}], id="surrounding-spaces"),
        pytest.param(":urn:uuid:U1", [{"value": "urn:uuid:U1"}], id="value-with-colons"),
        pytest.param("urn:uuid:U1", [{"scheme": "urn", "value": "uuid:U1"}], id="scheme-before-first-colon"),
        pytest.param("auxip:", [{"scheme": "auxip"}], id="scheme-only"),
        pytest.param(" auxip : ", [{"scheme": "auxip"}], id="scheme-only-surrounding-spaces"),
        pytest.param(
            "prip:U1,auxip:,U1",
            [{"scheme": "prip", "value": "U1"}, {"scheme": "auxip"}, {"value": "U1"}],
            id="scheme-only-among-others",
        ),
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
    """Searched identifiers are scheme:value, :value, value or scheme:, in strings, comma-separated strings or lists."""
    assert parse_external_ids(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(":", id="colon-only"),
        pytest.param("prip:U1, : ", id="colon-only-among-others"),
        pytest.param("", id="empty"),
        pytest.param(" , ", id="blank"),
        pytest.param([], id="empty-list"),
        pytest.param(None, id="null"),
        pytest.param(42, id="number"),
        pytest.param(["prip:U1", {"scheme": "prip"}], id="object"),
    ],
)
def test_parse_external_ids_refuses(raw):
    """A search without scheme nor value, or with a value that is not a string, is refused."""
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


@pytest.mark.parametrize(
    "node, expected",
    [
        pytest.param({"op": "=", "args": [PROP, "prip:U1"]}, contains({"scheme": "prip", "value": "U1"}), id="eq"),
        pytest.param({"op": "eq", "args": ["U1", PROP]}, contains({"value": "U1"}), id="eq-value-first"),
        pytest.param({"op": "=", "args": [PROP, "auxip:"]}, contains({"scheme": "auxip"}), id="scheme-only"),
        pytest.param(
            {"op": "in", "args": [PROP, ["prip:U1", "U2"]]},
            {"op": "or", "args": [contains({"scheme": "prip", "value": "U1"}), contains({"value": "U2"})]},
            id="in",
        ),
        pytest.param({"op": "in", "args": [PROP, ["U1"]]}, contains({"value": "U1"}), id="in-one-id"),
        pytest.param(
            {"op": "A_OVERLAPS", "args": [PROP, ["U1", "auxip:"]]},
            {"op": "or", "args": [contains({"value": "U1"}), contains({"scheme": "auxip"})]},
            id="a_overlaps",
        ),
        pytest.param(
            {"op": "a_contains", "args": [PROP, ["prip:U1", "U2", "auxip:"]]},
            contains({"scheme": "prip", "value": "U1"}, {"value": "U2"}, {"scheme": "auxip"}),
            id="a_contains",
        ),
    ],
)
def test_translate_external_ids_condition(node, expected):
    """Any of the ids gives one operator per id combined with or, all of the ids gives one operator."""
    assert translate_external_ids_filter(node) == expected


@pytest.mark.parametrize(
    "node",
    [
        pytest.param({"op": "=", "args": [PROP, "prip:U1"]}, id="equal"),
        pytest.param({"op": "in", "args": [PROP, ["U1", "auxip:"]]}, id="in"),
        pytest.param({"op": "a_contains", "args": [PROP, ["prip:U1", "U2"]]}, id="a_contains"),
        pytest.param(
            {"op": "and", "args": [OTHER, {"op": "not", "args": [{"op": "=", "args": [PROP, "U1"]}]}]},
            id="boolean",
        ),
    ],
)
def test_translated_filter_is_valid_cql2(node):
    """The translated filter is valid CQL2, as required by stac-fastapi-pgstac that validates it with cql2."""
    cql2.Expr(translate_external_ids_filter(node)).validate()  # pylint: disable=no-member


def test_translate_external_ids_in_boolean_filter():
    """Conditions are translated inside and/or/not, the rest of the filter is kept."""
    node = {
        "op": "or",
        "args": [
            {"op": "and", "args": [OTHER, {"op": "=", "args": [PROP, "U1"]}]},
            {"op": "not", "args": [{"op": "=", "args": [PROP, "U2"]}]},
        ],
    }
    assert translate_external_ids_filter(node) == {
        "op": "or",
        "args": [
            {"op": "and", "args": [OTHER, contains({"value": "U1"})]},
            {"op": "not", "args": [contains({"value": "U2"})]},
        ],
    }


def test_translate_filter_without_external_ids():
    """A filter without externalIds is not changed."""
    assert translate_external_ids_filter(OTHER) is OTHER


@pytest.mark.parametrize(
    "node",
    [
        pytest.param({"op": "=", "args": [PROP, ":"]}, id="colon-only"),
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
def test_translate_external_ids_refuses(node):
    """Any other use of externalIds is refused rather than giving a slow or wrong search."""
    with pytest.raises(HTTPException) as error:
        translate_external_ids_filter(node)
    assert error.value.status_code == 400


@pytest.mark.parametrize(
    "raw_filter, filter_lang, raw_external_ids, expected",
    [
        pytest.param(None, "cql2-text", None, None, id="no-filter"),
        pytest.param("width = 2500", "cql2-text", "", None, id="filter-without-external-ids"),
        pytest.param(OTHER, "cql2-json", [], None, id="json-filter-without-external-ids"),
        pytest.param(None, "cql2-text", "prip:", contains({"scheme": "prip"}), id="parameter"),
        pytest.param(
            "externalIds = 'U1'",
            "cql2-text",
            None,
            contains({"value": "U1"}),
            id="text-filter",
        ),
        pytest.param(
            '{"op": "=", "args": [{"property": "externalIds"}, "U1"]}',
            "cql2-json",
            None,
            contains({"value": "U1"}),
            id="json-string-filter",
        ),
        pytest.param(
            "width = 2500",
            "cql2-text",
            ["U1"],
            {"op": "and", "args": [OTHER, contains({"value": "U1"})]},
            id="parameter-and-filter",
        ),
    ],
)
def test_translate_external_ids_search(raw_filter, filter_lang, raw_external_ids, expected):
    """The externalIds parameter and the filter of a search are combined and translated."""
    assert translate_external_ids_search(raw_filter, filter_lang, raw_external_ids) == expected
