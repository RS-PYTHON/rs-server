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

"""Integration tests of the catalog search by externalIds, against a real pgstac database."""

# pylint: disable=missing-function-docstring,unused-argument

import json
from typing import Any

import fastapi
import pytest
from rs_server_catalog.app import app
from rs_server_catalog.middleware.request_manager import translate_external_ids_search

from tests.helpers import a_collection, a_feature, add_collection, delete_collection

OWNER = "extids"
COLLECTION = "EXTIDS"
OTHER_COLLECTION = "EXTIDS2"
PGSTAC_COLLECTION = f"{OWNER}_{COLLECTION}"
PGSTAC_OTHER_COLLECTION = f"{OWNER}_{OTHER_COLLECTION}"
ITEMS_URL = f"/catalog/collections/{OWNER}:{COLLECTION}/items"

U1 = "11111111-2222-3333-4444-555555555555"
U2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

# Items of the search dataset, by collection and id
DATASET: dict[str, dict[str, Any]] = {
    COLLECTION: {
        "item-prip": [{"scheme": "prip", "value": U1}],
        "item-multi": [
            {"scheme": "auxip", "value": U2},
            {"scheme": "other", "value": "X42"},
            {"scheme": "cadip", "value": "C3", "label": "with an additional field"},
        ],
        "item-same-value": [{"scheme": "cadip", "value": U1}],
        "item-none": None,
    },
    # Same item id as in the first collection
    OTHER_COLLECTION: {"item-prip": [{"scheme": "prip", "value": U1}]},
}


def a_feature_with_external_ids(item_id: str, external_ids: Any, collection: str = COLLECTION) -> dict:
    """Return a publishable feature, with the given externalIds (None = no externalIds)."""
    feature = a_feature(OWNER, item_id, collection).properties
    if external_ids is not None:
        feature["properties"]["externalIds"] = external_ids
    return feature


def search_response(client, method: str, external_ids: Any = None, collections=(PGSTAC_COLLECTION,), **params):
    """Search the catalog, by default in the test collection."""
    if external_ids is not None:
        params["externalIds"] = external_ids
    if collections:
        params["collections"] = list(collections)
    if method == "GET":
        for key, value in params.items():
            if isinstance(value, list):
                params[key] = ",".join(value)
            elif isinstance(value, dict):
                params[key] = json.dumps(value)
        return client.get("/catalog/search", params=params)
    return client.post("/catalog/search", json=params)


def search(client, method: str, external_ids: Any = None, **params) -> list[str]:
    """Search the test collection and return the sorted ids of the found items."""
    response = search_response(client, method, external_ids, **params)
    assert response.status_code == fastapi.status.HTTP_200_OK, response.text
    return sorted(feature["id"] for feature in response.json()["features"])


def assert_bad_request(response, message: str):
    assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST, response.text
    assert message in response.text


# Function scope: the S3 and OSAM credentials mocks needed to write in the catalog are only active during a test.
@pytest.fixture(name="external_ids_collections")
def external_ids_collections_fixture(client, init_buckets, external_ids_database):
    """Create the test collections with the search dataset, and delete them afterwards."""
    for collection, items in DATASET.items():
        delete_collection(client, OWNER, collection)
        add_collection(client, a_collection(OWNER, collection))
        for item_id, item_external_ids in items.items():
            response = client.post(
                f"/catalog/collections/{OWNER}:{collection}/items",
                json=a_feature_with_external_ids(item_id, item_external_ids, collection),
            )
            assert response.status_code == fastapi.status.HTTP_201_CREATED, response.text
    yield
    for collection in DATASET:
        delete_collection(client, OWNER, collection)


@pytest.mark.usefixtures("external_ids_collections")
class TestCatalogExternalIdsSearch:
    """Search items by externalIds with the externalIds parameter or with CQL2 filters."""

    @pytest.mark.parametrize("method", ["GET", "POST"])
    @pytest.mark.parametrize(
        "external_ids, expected",
        [
            pytest.param(f"prip:{U1}", ["item-prip"], id="scheme-and-value"),
            pytest.param(U1, ["item-prip", "item-same-value"], id="value-of-several-schemes"),
            pytest.param(f":{U2}", ["item-multi"], id="empty-scheme"),
            pytest.param(f"auxip:{U2}", ["item-multi"], id="first-of-several-ids"),
            pytest.param("other:X42", ["item-multi"], id="second-of-several-ids"),
            pytest.param("cadip:C3", ["item-multi"], id="id-with-additional-field"),
            pytest.param(f"prip:{U1},other:X42", ["item-multi", "item-prip"], id="comma-separated"),
            pytest.param([f"prip:{U1}", "X42"], ["item-multi", "item-prip"], id="list"),
            pytest.param(f" prip : {U1} ", ["item-prip"], id="surrounding-spaces"),
            pytest.param(f"auxip:{U1}", [], id="value-of-another-scheme"),
            pytest.param("prip:", ["item-prip"], id="scheme-only"),
            pytest.param("cadip:", ["item-multi", "item-same-value"], id="scheme-only-of-several-items"),
            pytest.param("other:", ["item-multi"], id="scheme-only-second-of-several-ids"),
            pytest.param("prip:,other:", ["item-multi", "item-prip"], id="scheme-only-comma-separated"),
            pytest.param(f"prip:,auxip:{U2}", ["item-multi", "item-prip"], id="scheme-only-and-scheme-and-value"),
            pytest.param(f"{U1}:", [], id="scheme-only-is-not-a-value"),
            pytest.param("unknown:", [], id="unknown-scheme"),
            pytest.param("prip:unknown", [], id="unknown-value"),
        ],
    )
    def test_search_with_external_ids_parameter(self, client, method, external_ids, expected):
        assert search(client, method, external_ids) == expected

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_search_with_external_ids_parameter_and_filter(self, client, method):
        """The externalIds parameter is combined with the filter with AND."""
        result = search(client, method, U1, filter="id = 'item-same-value'", **{"filter-lang": "cql2-text"})
        assert result == ["item-same-value"]

    @pytest.mark.parametrize("method", ["GET", "POST"])
    @pytest.mark.parametrize(
        "cql2_filter, expected",
        [
            pytest.param(f"externalIds = 'prip:{U1}'", ["item-prip"], id="equal"),
            pytest.param(f"'{U2}' = externalIds", ["item-multi"], id="equal-value-first"),
            pytest.param(f"externalIds IN ('prip:{U1}', 'other:X42')", ["item-multi", "item-prip"], id="in"),
            pytest.param(
                f"A_OVERLAPS(externalIds, ('auxip:{U2}', 'prip:unknown'))",
                ["item-multi"],
                id="a_overlaps",
            ),
            pytest.param(f"A_CONTAINS(externalIds, ('{U2}', 'other:X42'))", ["item-multi"], id="a_contains"),
            pytest.param(f"A_CONTAINS(externalIds, ('{U2}', 'prip:{U1}'))", [], id="a_contains-not-all"),
            pytest.param(
                f"externalIds = 'prip:{U1}' OR externalIds = 'X42'",
                ["item-multi", "item-prip"],
                id="or",
            ),
            pytest.param(f"externalIds = '{U1}' AND id = 'item-prip'", ["item-prip"], id="and-other-property"),
            pytest.param(
                f"NOT (externalIds = 'prip:{U1}') AND externalIds = '{U1}'",
                ["item-same-value"],
                id="not",
            ),
            # As for any property, an item without externalIds doesn't match, even negated
            pytest.param(f"NOT (externalIds = '{U1}')", ["item-multi"], id="not-only"),
            pytest.param("externalIds = 'cadip:'", ["item-multi", "item-same-value"], id="equal-scheme-only"),
            pytest.param(f"A_CONTAINS(externalIds, ('auxip:', '{U2}'))", ["item-multi"], id="a_contains-scheme-only"),
            pytest.param("A_CONTAINS(externalIds, ('cadip:', 'other:'))", ["item-multi"], id="a_contains-schemes"),
            pytest.param(f"A_CONTAINS(externalIds, ('prip:', '{U2}'))", [], id="a_contains-scheme-only-not-all"),
        ],
    )
    def test_search_with_cql2_text_filter(self, client, method, cql2_filter, expected):
        assert search(client, method, filter=cql2_filter, **{"filter-lang": "cql2-text"}) == expected

    @pytest.mark.parametrize("method", ["GET", "POST"])
    @pytest.mark.parametrize(
        "cql2_filter, expected",
        [
            pytest.param({"op": "=", "args": [{"property": "externalIds"}, f"prip:{U1}"]}, ["item-prip"], id="equal"),
            pytest.param(
                {"op": "in", "args": [{"property": "externalIds"}, [f"prip:{U1}", U2]]},
                ["item-multi", "item-prip"],
                id="in",
            ),
            pytest.param(
                {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "externalIds"}, "other:X42"]},
                        {"op": "=", "args": [{"property": "width"}, 2500]},
                    ],
                },
                ["item-multi"],
                id="and",
            ),
        ],
    )
    def test_search_with_cql2_json_filter(self, client, method, cql2_filter, expected):
        assert search(client, method, filter=cql2_filter, **{"filter-lang": "cql2-json"}) == expected

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_search_in_several_collections(self, client, method):
        """Items with the same id in several collections are told apart."""
        both = (PGSTAC_COLLECTION, PGSTAC_OTHER_COLLECTION)
        response = search_response(client, method, f"prip:{U1}", collections=both)
        assert response.status_code == fastapi.status.HTTP_200_OK, response.text
        found = sorted((feature["collection"], feature["id"]) for feature in response.json()["features"])
        assert found == [(COLLECTION, "item-prip"), (OTHER_COLLECTION, "item-prip")]

        response = search_response(client, method, f"prip:{U1}", collections=(PGSTAC_OTHER_COLLECTION,))
        assert [(f["collection"], f["id"]) for f in response.json()["features"]] == [
            (OTHER_COLLECTION, "item-prip"),
        ]

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_search_in_all_collections(self, client, method):
        """Without collections, the items of all the collections are searched."""
        response = search_response(client, method, f"prip:{U1},other:X42", collections=())
        assert response.status_code == fastapi.status.HTTP_200_OK, response.text
        found = sorted((feature["collection"], feature["id"]) for feature in response.json()["features"])
        assert found == [(COLLECTION, "item-multi"), (COLLECTION, "item-prip"), (OTHER_COLLECTION, "item-prip")]

    @pytest.mark.parametrize("method", ["GET", "POST"])
    @pytest.mark.parametrize(
        "params, message",
        [
            pytest.param({"externalIds": ":"}, "a scheme or a value is required", id="colon-only"),
            pytest.param(
                {"filter": "externalIds = ' : '", "filter-lang": "cql2-text"},
                "a scheme or a value is required",
                id="colon-only-filter",
            ),
            pytest.param({"externalIds": ","}, "No externalIds identifier to search", id="no-identifier"),
            pytest.param(
                {"filter": "externalIds LIKE '%U1%'", "filter-lang": "cql2-text"},
                "Unsupported externalIds filter",
                id="like",
            ),
            pytest.param(
                {"filter": "externalIds IS NULL", "filter-lang": "cql2-text"},
                "Unsupported externalIds filter",
                id="is-null",
            ),
            pytest.param(
                {"filter": f"A_EQUALS(externalIds, ('prip:{U1}'))", "filter-lang": "cql2-text"},
                "Unsupported externalIds filter",
                id="a_equals",
            ),
            pytest.param(
                {"filter": {"op": "=", "args": [{"property": "externalIds"}, 42]}, "filter-lang": "cql2-json"},
                "a string is expected",
                id="number",
            ),
        ],
    )
    def test_unsupported_search_is_refused(self, client, method, params, message):
        assert_bad_request(search_response(client, method, **params), message)

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_pagination(self, client, method):
        """The next page link repeats the translated filter, whose size doesn't depend on the matching items."""
        response = search_response(client, method, "cadip:", limit=1)
        assert response.status_code == fastapi.status.HTTP_200_OK, response.text
        first_page = [feature["id"] for feature in response.json()["features"]]
        next_link = next(link for link in response.json()["links"] if link["rel"] == "next")
        assert "item-" not in json.dumps(next_link), next_link

        if method == "GET":
            response = client.get(next_link["href"])
        else:
            response = client.post(next_link["href"], json=next_link["body"])
        assert response.status_code == fastapi.status.HTTP_200_OK, response.text
        second_page = [feature["id"] for feature in response.json()["features"]]
        assert sorted(first_page + second_page) == ["item-multi", "item-same-value"]

    def test_patched_external_ids_are_searchable(self, client):
        patch = {"properties": {"externalIds": [{"scheme": "prip", "value": "PATCHED"}]}}
        response = client.patch(f"{ITEMS_URL}/item-none", json=patch)
        assert response.status_code == fastapi.status.HTTP_200_OK, response.text
        assert search(client, "GET", "prip:PATCHED") == ["item-none"]

    @pytest.mark.parametrize("method", ["GET", "POST"])
    def test_special_characters(self, client, method):
        """Quotes, backslashes and non-ASCII characters are searched literally (pgstac quotes the operator argument)."""
        value = """it's a "quoted" \\ välue; DROP TABLE x; --"""
        patch = {"properties": {"externalIds": [{"scheme": "o'scheme", "value": value}]}}
        response = client.patch(f"{ITEMS_URL}/item-none", json=patch)
        assert response.status_code == fastapi.status.HTTP_200_OK, response.text
        assert search(client, method, [f"o'scheme:{value}"]) == ["item-none"]
        assert search(client, method, [f":{value}"]) == ["item-none"]
        assert search(client, method, ["o'scheme:"]) == ["item-none"]
        assert search(client, method, [f"{value}x"]) == []


@pytest.mark.usefixtures("external_ids_collections")
@pytest.mark.parametrize("external_ids", [f"prip:{U1}", U1, "prip:"])
def test_search_uses_the_index(client, external_ids):
    """The SQL generated by pgstac for the externalIds operator is served by the index of every partition."""
    search_body = {"filter-lang": "cql2-json", "filter": translate_external_ids_search(None, "", external_ids)}

    async def explain() -> str:
        async with app.state.readpool.acquire() as conn, conn.transaction():
            where = await conn.fetchval("SELECT pgstac.stac_search_to_where($1::text::jsonb)", json.dumps(search_body))
            # The test tables are too small for the planner to choose an index by itself
            await conn.execute("SET LOCAL enable_seqscan = off")
            rows = await conn.fetch(f"EXPLAIN SELECT id FROM pgstac.items WHERE {where}")
        return "\n".join(row[0] for row in rows)

    plan = client.portal.call(explain)
    assert "Seq Scan" not in plan, plan
    assert plan.count("Bitmap Index Scan on _items_") == plan.count("Bitmap Heap Scan on _items_") > 0, plan


@pytest.mark.usefixtures("external_ids_collections")
def test_index_is_kept_by_pgstac_maintenance(client):
    """pgstac doesn't see the index as an orphan, so it never tries to drop it from the partitions."""

    async def maintain_and_count_indexes() -> int:
        async with app.state.writepool.acquire() as conn:
            await conn.execute("SELECT pgstac.maintain_partitions(dropindexes => true)")
            return await conn.fetchval(
                """SELECT count(*) FROM pg_indexes
                WHERE schemaname = 'pgstac' AND indexdef LIKE '%externalIds%' AND indexdef LIKE '%jsonb_path_ops%'""",
            )

    # items, queryable_index_template and the partitions of the test collections at least
    assert client.portal.call(maintain_and_count_indexes) >= 2 + len(DATASET)
