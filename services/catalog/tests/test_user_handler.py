"""Unit tests for user_handler module."""

import pytest
from starlette.testclient import TestClient
from rs_server_catalog.app import app
from rs_server_catalog.user_handler import *


@pytest.fixture
def client():
    """Test the FastAPI application."""
    with TestClient(app) as client:
        yield client
    
@pytest.fixture
def collection_toto_1() -> dict:
    """Create a collection for testing."""
    return {
        "Value" : "1",
        "id" : "toto_S1_L1",
        "count" : "15",
    }

@pytest.fixture
def collection_toto_1_output() -> dict:
    """Create a collection for testing."""
    return {
        "Value" : "1",
        "id" : "S1_L1",
        "count" : "15",
    }

@pytest.fixture
def collection_toto_2() -> dict:
    """Create a collection for testing."""
    return {
        "Value" : "65",
        "id" : "toto_S1_L2",
        "count" : "54",
    }

@pytest.fixture
def collection_titi_1() -> dict:
    """Create a collection for testing."""
    return {
        "Value" : "97",
        "id" : "titi_S2_L2",
        "count" : "2",
    }

@pytest.fixture
def collection_titi_2() -> dict:
    """Create a collection for testing."""
    return {
        "Value" : "109",
        "id" : "titi_S2_L1",
        "count" : "17",
    }

@pytest.fixture
def collections(collection_toto_1, collection_toto_2, collection_titi_1, collection_titi_2) -> list[dict]:
    """Create a list of collections for testing."""
    return [collection_toto_1, collection_toto_2, collection_titi_1, collection_titi_2]

@pytest.fixture
def feature() -> dict:
    """Create a feature for testing."""
    return {
        "Geometry" : [(43,44),(72,15),(78,35),(65,82)],
        "collection" : "titi_S1_L1",
    }

@pytest.fixture
def feature_output() -> dict:
    """Create a feature for testing."""
    return {
        "Geometry" : [(43,44),(72,15),(78,35),(65,82)],
        "collection" : "S1_L1",
    }

def test_(client):
    """Test the fastAPI client with the middleware."""
    response = client.get("/catalog/Toto/collections/joplin/items")
    assert response.status_code == 200

class TestRemovePrefix:
    """This Class contains unit tests for the function remove_user_prefix."""

    def test_fails_if_root_url(self):
        with pytest.raises(ValueError) as exc_info:
            remove_user_prefix("/")
        assert str(exc_info.value) == "URL (/) is invalid."

    def test_remove_the_catalog_prefix(self):
        assert remove_user_prefix("/catalog") == "/"

    def test_remove_user_and_catalog_prefix(self):
        assert remove_user_prefix("/catalog/Toto/collections") == "/collections" 

    def test_remove_catalog_and_replace_user(self):
        assert remove_user_prefix("/catalog/Toto/collections/joplin") == "/collections/Toto_joplin" 

    def test_remove_catalog_replace_user_with_items(self):
        assert remove_user_prefix("/catalog/Toto/collections/joplin/items") == "/collections/Toto_joplin/items" 

    def test_ignore_if_unknown_endpoint(self):
        assert remove_user_prefix("/not/found") == "/not/found" # This behavior is to be determined

class TestAddUserPrefix:
    """This Class contains unit tests for the function add_user_prefix."""

    def test_return_catalog_if_no_user(self):
        assert add_user_prefix("/", "", "") == "/catalog"

    def test_add_prefix_and_user_prefix(self):
        assert add_user_prefix("/collections", "toto", "") == "/catalog/toto/collections"
    
    def test_add_prefix_and_replace_user(self):
        assert add_user_prefix("collections/toto_joplin", "toto", "joplin") == "/catalog/toto/collections/joplin"

    def test_add_prefix_replace_user_with_items(self):
        assert add_user_prefix("collections/toto_joplin/items", "toto", "joplin") == "/catalog/toto/collections/joplin/items"
    
    def test_fails_if_invalid_URL(self):
        with pytest.raises(ValueError) as exc_info:
            add_user_prefix("NOT/FOUND", "", "")
        assert str(exc_info.value) == "URL NOT/FOUND is invalid."


class TestRemoveUserFromCollection:
    """This Class contains unit tests for the function remove_user_from_collection."""

    def test_remove_the_user_in_the_collection_id_property(self, collection_toto_1, collection_toto_1_output):
        assert remove_user_from_collection(collection_toto_1, "toto") == collection_toto_1_output

    def test_does_nothing_if_user_is_not_found(self, collection_toto_1): # This behavior is to be determined
        assert remove_user_from_collection(collection_toto_1, "titi") == collection_toto_1 

class TestRemoveUserFromFeature:
    """This Class contains unit tests for the function remove_user_from_feature."""

    def test_remove_the_user_in_the_feature_id_property(self, feature, feature_output):
        assert remove_user_from_feature(feature, "titi") == feature_output

    def test_does_nothing_if_user_is_not_found(self, feature): # This behavior is to be determined
        assert remove_user_from_feature(feature, "toto") == feature 

class TestFilterCollections:
    """This Class contains unit tests for the function filter_collections"""

    def test_get_all_collections_with_toto_in_the_id_property(self, collection_toto_1, collection_toto_2, collections):
        assert filter_collections(collections, "toto") == [collection_toto_1, collection_toto_2]

    def test_get_nothing_if_the_user_is_not_found(self, collections):
        assert filter_collections(collections, "NOTFOUND") == []