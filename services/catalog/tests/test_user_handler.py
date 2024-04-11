"""Unit tests for user_handler module."""

import pytest
from rs_server_catalog.user_handler import (
    add_user_prefix,
    filter_collections,
    remove_user_from_collection,
    remove_user_from_feature,
    reroute_url,
)


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


class TestRemovePrefix:  # pylint: disable=missing-function-docstring
    """This Class contains unit tests for the function remove_user_prefix."""

    def test_fails_if_root_url(self):
        with pytest.raises(ValueError) as exc_info:
            reroute_url("/", "GET")
        assert str(exc_info.value) == "URL (/) is invalid."

    def test_remove_the_catalog_prefix(self):
        assert reroute_url("/catalog/catalogs/Toto", "GET")[0] == ("/")

    # Disabled for moment
    # def test_landing_page(self):
    #     assert reroute_url("/catalog/Toto", "GET") == "/", {"owner_id": "Toto", "collection_id": "", "item_id": ""}

    def test_item_id(self):
        result = reroute_url("/catalog/collections/Toto:joplin/items/fe916452-ba6f-4631-9154-c249924a122d", "GET")
        assert result[0] == "/collections/Toto_joplin/items/fe916452-ba6f-4631-9154-c249924a122d"
        assert result[1] == {
            "owner_id": "Toto",
            "collection_id": "joplin",
            "item_id": "fe916452-ba6f-4631-9154-c249924a122d",
        }

    def test_fails_if_unknown_endpoint(self):
        with pytest.raises(ValueError) as exc_info:
            reroute_url("/not/found", "GET")
        assert str(exc_info.value) == "Path /not/found is invalid."

    def test_work_with_ping_endpoinst(self):
        assert reroute_url("/_mgmt/ping", "GET")[0] == ("/_mgmt/ping")


class TestAddUserPrefix:  # pylint: disable=missing-function-docstring
    """This Class contains unit tests for the function add_user_prefix."""

    def test_return_catalog_if_no_user(self):
        assert add_user_prefix("/", "toto", "") == "/catalog/toto"

    def test_add_prefix_and_user_prefix(self):
        assert add_user_prefix("/collections", "toto", "") == "/catalog/toto/collections"

    def test_add_prefix_and_replace_user(self):
        result = add_user_prefix("/collections/toto_joplin", "toto", "joplin")
        assert result == "/catalog/toto/collections/joplin"

    def test_add_prefix_replace_user_with_items(self):
        result = add_user_prefix("/collections/toto_joplin/items", "toto", "joplin")
        assert result == "/catalog/toto/collections/joplin/items"

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
