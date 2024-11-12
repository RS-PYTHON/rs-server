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

"""Unit tests for user_handler module."""

import getpass

import pytest
from rs_server_catalog.user_handler import (
    add_user_prefix,
    filter_collections,
    get_user,
    remove_user_from_collection,
    remove_user_from_feature,
    reroute_url,
)
from starlette.requests import Request


@pytest.fixture(name="request_ids")
def request_id_example() -> dict:
    """Create a request_ids disctionary to test the reroute url function calls"""
    return {"auth_roles": "", "user_login": "", "owner_id": "", "collection_ids": [], "item_id": ""}


@pytest.fixture(name="collection_toto_1")
def collection_toto_1_fixture() -> dict:
    """Create a collection for testing."""
    return {
        "Value": "1",
        "id": "toto_S1_L1",
        "count": "15",
    }


@pytest.fixture(name="collection_toto_1_output")
def collection_toto_1_output_fixture() -> dict:
    """Create a collection for testing."""
    return {
        "Value": "1",
        "id": "S1_L1",
        "count": "15",
    }


@pytest.fixture(name="collection_toto_2")
def collection_toto_2_fixture() -> dict:
    """Create a collection for testing."""
    return {
        "Value": "65",
        "id": "toto_S1_L2",
        "count": "54",
    }


@pytest.fixture(name="collection_titi_1")
def collection_titi_1_fixture() -> dict:
    """Create a collection for testing."""
    return {
        "Value": "97",
        "id": "titi_S2_L2",
        "count": "2",
    }


@pytest.fixture(name="collection_titi_2")
def collection_titi_2_fixture() -> dict:
    """Create a collection for testing."""
    return {
        "Value": "109",
        "id": "titi_S2_L1",
        "count": "17",
    }


@pytest.fixture(name="collections")
def collections_fixture(
    collection_toto_1: dict,
    collection_toto_2: dict,
    collection_titi_1: dict,
    collection_titi_2: dict,
) -> list[dict]:
    """Create a list of collections for testing."""
    return [collection_toto_1, collection_toto_2, collection_titi_1, collection_titi_2]


@pytest.fixture(name="feature")
def feature_fixture() -> dict:
    """Create a feature for testing."""
    return {
        "Geometry": [(43, 44), (72, 15), (78, 35), (65, 82)],
        "collection": "titi_S1_L1",
    }


@pytest.fixture(name="feature_output")
def feature_output_fixture() -> dict:
    """Create a feature for testing."""
    return {
        "Geometry": [(43, 44), (72, 15), (78, 35), (65, 82)],
        "collection": "S1_L1",
    }


def test_get_user():
    """This function tests the get_user()"""
    assert get_user("pyteam", "apikey_user") == "pyteam"
    assert get_user(None, "apikey_user") == "apikey_user"
    assert get_user(None, None) == getpass.getuser()


class TestRemovePrefix:  # pylint: disable=missing-function-docstring
    """This Class contains unit tests for the function remove_user_prefix."""

    def test_root_url(self, request_ids):
        request = Request(
            scope={"type": "http", "method": "GET", "path": "/", "query_string": "", "user": "", "headers": {}},
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == "/"

    def test_item_id(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/collections/Toto:joplin/items/fe916452-ba6f-4631-9154-c249924a122d",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == "/collections/Toto_joplin/items/fe916452-ba6f-4631-9154-c249924a122d"
        valid_request_ids = {
            "owner_id": "Toto",
            "collection_ids": ["joplin"],
            "item_id": "fe916452-ba6f-4631-9154-c249924a122d",
        }
        assert all(request_ids.get(key, None) == val for key, val in valid_request_ids.items())

    # NOTE: The following function is the test for local mode, when there is no apikey and the ownerId
    # is missing from the endpoint. The tests when the apikey exists (thus in cluster mode) are implemented
    # in test_authetication_catalog.py
    def test_item_id_without_user(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/collections/joplin/items/fe916452-ba6f-4631-9154-c249924a122d",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert (
            request.scope["path"]
            == f"/collections/{getpass.getuser()}_joplin/items/fe916452-ba6f-4631-9154-c249924a122d"
        )
        valid_request_ids = {
            "owner_id": getpass.getuser(),
            "collection_ids": ["joplin"],
            "item_id": "fe916452-ba6f-4631-9154-c249924a122d",
        }
        assert all(request_ids.get(key, None) == val for key, val in valid_request_ids.items())

    def test_fails_if_unknown_endpoint(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/not/found",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        valid_request_ids = request_ids.copy()
        reroute_url(request, request_ids)
        assert request.scope["path"] == ""
        assert request_ids == valid_request_ids

    def test_work_with_ping_endpoinst(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/_mgmt/ping",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == ("/_mgmt/ping")

    def test_reroute_oauth2(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/docs/oauth2-redirect",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == "/docs/oauth2-redirect"

    def test_reroute_queryables(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/queryables",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == "/queryables"

    def test_search_collection(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/collections/toto:S1_L1/search",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == "/collections/toto:S1_L1/search"
        # Check that the valid dictionary is a subset of the output dictionary
        valid_request_ids = {
            "owner_id": "toto",
            "collection_ids": ["toto_S1_L1"],
            "item_id": "",
        }
        assert all(request_ids.get(key, None) == val for key, val in valid_request_ids.items())

    def test_search_collection_with_implicit_owner(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/collections/S1_L1/search",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == "/collections/S1_L1/search"

    def test_reroute_collections_queryables(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/collections/toto:S1_L1/queryables",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)

        assert request.scope["path"] == "/collections/toto_S1_L1/queryables"
        # Check that the valid dictionary is a subset of the output dictionary
        valid_request_ids = {
            "owner_id": "toto",
            "collection_ids": ["S1_L1"],
            "item_id": "",
        }
        assert all(request_ids.get(key, None) == val for key, val in valid_request_ids.items())

    def test_reroute_bulk_items(self, request_ids):
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/collections/toto:S1_L1/bulk_items",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)

        assert request.scope["path"] == "/collections/toto_S1_L1/bulk_items"
        # Check that the valid dictionary is a subset of the output dictionary
        valid_request_ids = {
            "owner_id": "toto",
            "collection_ids": ["S1_L1"],
            "item_id": "",
        }
        assert all(request_ids.get(key, None) == val for key, val in valid_request_ids.items())


class TestAddUserPrefix:  # pylint: disable=missing-function-docstring
    """This Class contains unit tests for the function add_user_prefix."""

    def test_add_prefix_and_user_prefix(self):
        assert add_user_prefix("/collections", "toto", "") == "/catalog/collections"

    def test_add_prefix_and_replace_user(self):
        result = add_user_prefix("/collections/toto_joplin", "toto", "joplin")
        assert result == "/catalog/collections/toto:joplin"

    def test_add_prefix_replace_user_with_items(self):
        result = add_user_prefix("/collections/toto_joplin/items", "toto", "joplin")
        assert result == "/catalog/collections/toto:joplin/items"

    def test_add_prefix_replace_user_with_queryables(self):
        result = add_user_prefix("/collections/toto_joplin/queryables", "toto", "joplin")
        assert result == "/catalog/collections/toto:joplin/queryables"

    def test_does_nothing_if_url_not_found(self):
        assert add_user_prefix("/NOT/FOUND", "toto", "joplin") == "/NOT/FOUND"


class TestRemoveUserFromCollection:  # pylint: disable=missing-function-docstring
    """This Class contains unit tests for the function remove_user_from_collection."""

    def test_remove_the_user_in_the_collection_id_property(
        self,
        collection_toto_1: dict,
        collection_toto_1_output: dict,
    ):
        assert remove_user_from_collection(collection_toto_1, "toto") == collection_toto_1_output

    def test_does_nothing_if_user_is_not_found(self, collection_toto_1: dict):
        assert remove_user_from_collection(collection_toto_1, "titi") == collection_toto_1


class TestRemoveUserFromFeature:  # pylint: disable=missing-function-docstring
    """This Class contains unit tests for the function remove_user_from_feature."""

    def test_remove_the_user_in_the_feature_id_property(self, feature: dict, feature_output: dict):
        assert remove_user_from_feature(feature, "titi") == feature_output

    def test_does_nothing_if_user_is_not_found(self, feature: dict):  # This behavior is to be determined
        assert remove_user_from_feature(feature, "toto") == feature


class TestFilterCollections:  # pylint: disable=missing-function-docstring
    """This Class contains unit tests for the function filter_collections"""

    def test_get_nothing_if_the_user_is_not_found(self, collections: list[dict]):
        assert filter_collections(collections, "NOTFOUND") == []

    def test_get_all_collections_with_toto_in_the_id_property(
        self,
        collection_toto_1: dict,
        collection_toto_2: dict,
        collections: list[dict],
    ):
        assert filter_collections(collections, "toto") == [collection_toto_1, collection_toto_2]
