# Copyright 2024 CS Group
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

"""Integration tests for search endpoint of user_catalog module."""

# pylint: disable=missing-function-docstring
# pylint: disable=unused-argument

import json
import pathlib
from typing import Any

import fastapi
import pytest


class TestCatalogSearchEndpoint:
    """This class contains integration tests for the endpoint '/catalog/search'."""

    def test_search_endpoint_with_ids_and_collections(self, client):
        test_params = {"ids": "fe916452-ba6f-4631-9154-c249924a122d", "collections": "toto_S1_L1"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 1

    def test_search_endpoint_with_filter_owner_id_and_other(self, client):
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500 AND owner='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 2

        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=3000 AND owner='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 0

    def test_search_endpoint_with_filter_owner_id_only(self, client):
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "owner='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 2

    def test_search_endpoint_without_collections(self, client):
        test_params = {"filter-lang": "cql2-text", "filter": "owner='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 3

    def test_search_endpoint_without_filter(self, client):
        test_params = {"collections": "toto_S1_L1", "limit": "5"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK

    def test_search_endpoint_without_owner_id(self, client):
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND

    def test_search_endpoint_with_specific_filter(self, client):
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500", "owner": "toto"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 2  # behavior to be determined

    def test_post_search_endpoint(self, client):
        test_json = {
            "collections": ["S1_L1"],
            "filter-lang": "cql2-json",
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "owner"}, "toto"]},
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                ],
            },
        }

        response = client.post("/catalog/search", json=test_json)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 2

    def test_post_search_endpoint_with_no_filter_lang(self, client):
        test_json = {
            "collections": ["S1_L1"],
            # Here we remove the filter-lang field and check that we insert a default filter-lang.
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "owner"}, "toto"]},
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                ],
            },
        }
        response = client.post("/catalog/search", json=test_json)
        assert response.status_code == fastapi.status.HTTP_200_OK

    def test_search_in_unexisting_collection(self, client):
        """Test that if the collection does not exist, an HTTP 404 error is returned."""

        # Test for GET /catalog/search
        test_params = {"collections": ["S1_L1"], "filter": "owner='tata'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND  # Checking with unexisting owner_id
        test_params = {"collections": ["notfound"], "filter": "owner='toto'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND  # Checking with unexisting collection_id

        # Test for POST /catalog/search
        test_json = {
            "collections": ["S1_L1"],
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "owner"}, "tata"]},
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                ],
            },
        }

        response = client.post("/catalog/search", json=test_json)
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND  # Checking with unexisting owner_id

        test_json = {
            "collections": ["notfound"],
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "owner"}, "toto"]},
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                ],
            },
        }

        response = client.post("/catalog/search", json=test_json)
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND  # Checking with unexisting collection_id

    def test_search_with_collections_and_filter(self, client):
        test_params = {"collections": ["toto_S1_L1"], "filter": "width=2500"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 2

        test_json = {
            "collections": ["toto_S1_L1"],
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                    {"op": "=", "args": [{"property": "height"}, 2500]},
                ],
            },
        }
        response = client.post("/catalog/search", json=test_json)
        assert response.status_code == fastapi.status.HTTP_200_OK

    @pytest.mark.parametrize(
        "method",
        ["POST", "GET"],
    )
    def test_search_using_several_collections(self, client, method):
        """Test a search request involving several collections (with both POST and GET method)"""
        # Search items on several collections without using implicit naming feature
        test_json: dict[str, Any] = {}
        test_params = {}

        if method == "POST":
            test_json = {
                "collections": ["toto_S1_L1", "toto_S2_L3"],
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {
                "collections": "toto_S1_L1,toto_S2_L3",
                "filter-lang": "cql2-text",
            }
            response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        assert len(json.loads(response.content)["features"]) == 3

        # Use implicit naming mechanism for some collections of the list + specify owner in the content/query parameters
        if method == "POST":
            test_json = {
                "collections": ["S1_L1", "S2_L3"],
                "owner": "toto",
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {
                "collections": "S1_L1,toto_S2_L3",
                "filter-lang": "cql2-text",
                "owner": "toto",
            }
            response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        assert len(json.loads(response.content)["features"]) == 3

        # Use implicit naming mechanism for some collections of the list + specify owner in the filter
        if method == "POST":
            test_json = {
                "collections": ["S1_L1", "toto_S2_L3"],
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "owner"}, "toto"]},
                    ],
                },
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {
                "collections": "S1_L1,toto_S2_L3",
                "filter-lang": "cql2-text",
                "filter": "width=2500 AND owner='toto'",
            }
            response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        assert response.status_code == fastapi.status.HTTP_200_OK
        assert len(json.loads(response.content)["features"]) == 3

        # Implicit naming mechanism will not produce the right owner_id if we don't specify it in the
        # content/query parameters or in the filter
        if method == "POST":
            test_json = {
                "collections": ["S1_L1", "toto_S2_L3"],
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {"collections": "toto_S1_L1,S2_L3", "filter": "width=2500"}
            response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND

        # Check that we get an error if at least one existing collection doesn't exist
        if method == "POST":
            test_json = {
                "collections": ["S1_L1", "unexisting_collection"],
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "owner"}, "toto"]},
                    ],
                },
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {"collections": "toto_S1_L1,unexisting_collection", "filter": "width=2500"}
            response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND

    def test_queryables(self, client):
        for path in "/catalog/queryables", "/catalog/collections/toto:S1_L1/queryables":
            try:
                response = client.get(path)
                content = json.loads(response.content)
                with open("queryables.json", "w", encoding="utf-8") as f:
                    json.dump(content, f, indent=2)
                assert response.status_code == fastapi.status.HTTP_200_OK
            except Exception as e:
                raise RuntimeError("error") from e
            finally:
                pathlib.Path("queryables.json").unlink(missing_ok=True)


class TestCatalogSearchEndpointWithTemporalFilters:
    """This class contains integration tests for the endpoint '/catalog/search' using advanced temporal filters.

    The filters used are the ones defined here:
        https://pforge-exchange2.astrium.eads.net/confluence/display/COPRS/4.+External+data+selection+policies

    The test data follows the specifications examples. The time intervals used for the tests are :
        t0-dt0 = 2025-03-01T00:00:00Z
        t1+dt1 = 2025-06-01T00:00:00Z
    """

    @pytest.mark.parametrize(
        "method",
        ["POST", "GET"],
    )
    def test_filter_valcover(self, client, method, temporal_filters_test_data):
        """Test for ValCover filter on search endpoint with POST and GET methods.
        This filter returns all files entirely covering the given time interval.
        With our test data from 'temporal_filters_test_data.json' this corresponds to R2 and R3.
        """
        if method == "POST":
            test_json = {
                "collections": ["temporal_filters_test_data"],
                "owner": "testowner",
                "filter": {
                    "op": "t_contains",
                    "args": [
                        {"interval": [{"property": "start_datetime"}, {"property": "end_datetime"}]},
                        {"interval": ["2025-03-01T00:00:00Z", "2025-06-01T00:00:00Z"]},
                    ],
                },
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {
                "collections": "temporal_filters_test_data",
                "filter-lang": "cql2-text",
                "owner": "testowner",
                "filter": "T_CONTAINS(INTERVAL(start_datetime,end_datetime),"
                "INTERVAL(TIMESTAMP('2025-03-01T00:00:00Z'),TIMESTAMP('2025-06-01T00:00:00Z')))",
            }
            response = client.get("/catalog/search", params=test_params)

        assert response.status_code == fastapi.status.HTTP_200_OK
        assert "features" in response.json() and len(response.json()["features"]) == 2
        assert response.json()["features"][0]["id"] == "R2" and response.json()["features"][1]["id"] == "R3"

    @pytest.mark.parametrize(
        "method",
        ["POST", "GET"],
    )
    def test_filter_latestvalcover(self, client, method, temporal_filters_test_data):
        """Test for LatestValCover filter on search endpoint with POST and GET methods.
        This filter returns the latest file entirely covering the given time interval.
        With our test data from 'temporal_filters_test_data.json' this corresponds to R3.
        """
        if method == "POST":
            test_json = {
                "collections": ["temporal_filters_test_data"],
                "owner": "testowner",
                "filter": {
                    "op": "t_contains",
                    "args": [
                        {"interval": [{"property": "start_datetime"}, {"property": "end_datetime"}]},
                        {"interval": ["2025-03-01T00:00:00Z", "2025-06-01T00:00:00Z"]},
                    ],
                },
                "sortby": [{"field": "created", "direction": "desc"}],
                "limit": 1,
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {
                "collections": "temporal_filters_test_data",
                "filter-lang": "cql2-text",
                "owner": "testowner",
                "filter": "T_CONTAINS(INTERVAL(start_datetime,end_datetime),"
                "INTERVAL(TIMESTAMP('2025-03-01T00:00:00Z'),TIMESTAMP('2025-06-01T00:00:00Z')))",
                "sortby": "-properties.created",
                "limit": "1",
            }
            response = client.get("/catalog/search", params=test_params)

        assert response.status_code == fastapi.status.HTTP_200_OK
        assert "features" in response.json() and len(response.json()["features"]) == 1
        assert response.json()["features"][0]["id"] == "R3"

    @pytest.mark.parametrize(
        "method",
        ["POST", "GET"],
    )
    def test_filter_valintersect(self, client, method, temporal_filters_test_data):
        """Test for ValIntersect filter on search endpoint with POST and GET methods.
        This filter returns all files that cover partly the given time interval.
        With our test data from 'temporal_filters_test_data.json' this corresponds to R1, R2, R3 and R4.
        """
        if method == "POST":
            test_json = {
                "collections": ["temporal_filters_test_data"],
                "owner": "testowner",
                "filter": {
                    "op": "t_intersects",
                    "args": [
                        {"interval": [{"property": "start_datetime"}, {"property": "end_datetime"}]},
                        {"interval": ["2025-03-01T00:00:00Z", "2025-06-01T00:00:00Z"]},
                    ],
                },
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {
                "collections": "temporal_filters_test_data",
                "filter-lang": "cql2-text",
                "owner": "testowner",
                "filter": "T_INTERSECTS(INTERVAL(start_datetime,end_datetime),"
                "INTERVAL(TIMESTAMP('2025-03-01T00:00:00Z'),TIMESTAMP('2025-06-01T00:00:00Z')))",
            }
            response = client.get("/catalog/search", params=test_params)

        assert response.status_code == fastapi.status.HTTP_200_OK
        assert "features" in response.json() and len(response.json()["features"]) == 4

        list_of_ids = [feature["id"] for feature in response.json()["features"]]
        assert sorted(["R1", "R2", "R3", "R4"]) == sorted(list_of_ids)

    @pytest.mark.parametrize(
        "method",
        ["POST", "GET"],
    )
    def test_filter_latestvalintersect(self, client, method, temporal_filters_test_data):
        """Test for LatestValIntersect filter on search endpoint with POST and GET methods.
        This filter returns the latest file that covers partly the given time interval.
        With our test data from 'temporal_filters_test_data.json' this corresponds to R4.
        """
        if method == "POST":
            test_json = {
                "collections": ["temporal_filters_test_data"],
                "owner": "testowner",
                "filter": {
                    "op": "t_intersects",
                    "args": [
                        {"interval": [{"property": "start_datetime"}, {"property": "end_datetime"}]},
                        {"interval": ["2025-03-01T00:00:00Z", "2025-06-01T00:00:00Z"]},
                    ],
                },
                "sortby": [{"field": "created", "direction": "desc"}],
                "limit": 1,
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {
                "collections": "temporal_filters_test_data",
                "filter-lang": "cql2-text",
                "owner": "testowner",
                "filter": "T_INTERSECTS(INTERVAL(start_datetime,end_datetime),"
                "INTERVAL(TIMESTAMP('2025-03-01T00:00:00Z'),TIMESTAMP('2025-06-01T00:00:00Z')))",
                "sortby": "-properties.created",
                "limit": "1",
            }
            response = client.get("/catalog/search", params=test_params)

        assert response.status_code == fastapi.status.HTTP_200_OK
        assert "features" in response.json() and len(response.json()["features"]) == 1
        assert response.json()["features"][0]["id"] == "R4"

    @pytest.mark.parametrize(
        "method",
        ["POST", "GET"],
    )
    def test_filter_latestvalidity(self, client, method, temporal_filters_test_data):
        """Test for LatestValidity filter on search endpoint with POST and GET methods.
        This filter returns the file with the latest Validity Start Time.
        With our test data from 'temporal_filters_test_data.json' this corresponds to R6.
        """
        if method == "POST":
            test_json = {
                "collections": ["temporal_filters_test_data"],
                "owner": "testowner",
                "sortby": [{"field": "start_datetime", "direction": "desc"}],
                "limit": 1,
            }
            response = client.post("/catalog/search", json=test_json)
        else:
            test_params = {
                "collections": "temporal_filters_test_data",
                "filter-lang": "cql2-text",
                "owner": "testowner",
                "sortby": "-properties.start_datetime",
                "limit": "1",
            }
            response = client.get("/catalog/search", params=test_params)

        assert response.status_code == fastapi.status.HTTP_200_OK
        assert "features" in response.json() and len(response.json()["features"]) == 1
        assert response.json()["features"][0]["id"] == "R6"
