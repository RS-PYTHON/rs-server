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

"""Unit tests for user_handler module."""

import getpass

import pytest
from rs_server_catalog.data_management.user_handler import (
    adapt_object_links,
    add_user_prefix,
    get_user,
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


def test_get_user():
    """This function tests the get_user()"""
    assert get_user("pyteam", "apikey_user") == "pyteam"
    assert get_user(None, "apikey_user") == "apikey_user"
    assert get_user(None, None) == getpass.getuser()


class TestRerouteURL:  # pylint: disable=missing-function-docstring
    """This Class contains unit tests for the function reroute_url."""

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
        assert request.scope["path"] == "/catalog/collections/Toto_joplin/items/fe916452-ba6f-4631-9154-c249924a122d"
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
            == f"/catalog/collections/{getpass.getuser()}_joplin/items/fe916452-ba6f-4631-9154-c249924a122d"
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
        assert request.scope["path"] == "/catalog/docs/oauth2-redirect"

    @pytest.mark.parametrize(
        "path, expected",
        [
            ("/catalog/", "/catalog/"),
            ("/catalog", "/catalog"),
        ],
    )
    def test_reroute_catalog(self, request_ids, path, expected):
        """Test that reroute_url modifies "/catalog" and "/catalog/" to the root URL ("/")."""
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": path,
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == expected

    def test_reroute_catalog_api(self, request_ids):
        """Test that reroute_url modifies "/catalog/api" to the "/api"."""
        request = Request(
            scope={
                "type": "http",
                "method": "GET",
                "path": "/catalog/api",
                "query_string": "",
                "user": "",
                "headers": {},
            },
        )
        reroute_url(request, request_ids)
        assert request.scope["path"] == "/catalog/api"

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
        assert request.scope["path"] == "/catalog/queryables"

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

        assert request.scope["path"] == "/catalog/collections/toto_S1_L1/queryables"
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

        assert request.scope["path"] == "/catalog/collections/toto_S1_L1/bulk_items"
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
        assert add_user_prefix("/catalog/collections", "toto", "") == "/catalog/collections"

    def test_add_prefix_and_replace_user(self):
        result = add_user_prefix("/catalog/collections/toto_joplin", "toto", "joplin")
        assert result == "/catalog/collections/toto:joplin"

    def test_add_prefix_replace_user_with_items(self):
        result = add_user_prefix("/catalog/collections/toto_joplin/items", "toto", "joplin")
        assert result == "/catalog/collections/toto:joplin/items"

    def test_add_prefix_replace_user_with_queryables(self):
        result = add_user_prefix("/catalog/collections/toto_joplin/queryables", "toto", "joplin")
        assert result == "/catalog/collections/toto:joplin/queryables"

    def test_does_nothing_if_url_not_found(self):
        assert add_user_prefix("/NOT/FOUND", "toto", "joplin") == "/NOT/FOUND"


class TestAdaptObjectLinks:  # pylint: disable=missing-function-docstring
    """Unit tests for adapt_object_links: the ids keep their owner prefix, but the links never contain it."""

    def test_collection_id_is_kept_and_links_are_adapted(self):
        collection = {
            "id": "toto_joplin",
            "owner": "toto",
            "links": [{"rel": "self", "href": "http://testserver/catalog/collections/toto_joplin"}],
        }
        result = adapt_object_links(collection)
        assert result["id"] == "toto_joplin"
        assert result["links"][0]["href"] == "http://testserver/catalog/collections/toto:joplin"

    def test_item_collection_is_kept_and_links_are_adapted(self):
        item = {
            "id": "item1",
            "collection": "toto_joplin",
            "properties": {"owner": "toto"},
            "links": [{"rel": "self", "href": "http://testserver/catalog/collections/toto_joplin/items/item1"}],
        }
        result = adapt_object_links(item)
        assert result["collection"] == "toto_joplin"
        assert result["links"][0]["href"] == "http://testserver/catalog/collections/toto:joplin/items/item1"

    def test_current_user_is_the_default_owner(self):
        collection = {
            "id": "toto_joplin",
            "links": [{"rel": "items", "href": "http://testserver/catalog/collections/toto_joplin/items"}],
        }
        result = adapt_object_links(collection, "toto")
        assert result["id"] == "toto_joplin"
        assert result["links"][0]["href"] == "http://testserver/catalog/collections/toto:joplin/items"

    def test_nothing_is_changed_if_the_id_has_no_owner_prefix(self):
        collection = {
            "id": "joplin",
            "owner": "toto",
            "links": [{"rel": "self", "href": "http://testserver/catalog/collections/joplin"}],
        }
        result = adapt_object_links(collection)
        assert result["id"] == "joplin"
        assert result["links"][0]["href"] == "http://testserver/catalog/collections/joplin"
