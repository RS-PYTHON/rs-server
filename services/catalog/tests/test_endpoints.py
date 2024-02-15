import json

import pytest

from tests.conftest import add_collection, add_feature


@pytest.mark.integration
@pytest.fixture(scope="session", autouse=True)
def setup_database(
    client, toto_s1_l1, toto_s2_l3, titi_s2_l1, feature_toto_S1_L1_0, feature_toto_S1_L1_1, feature_titi_S2_L1_0
):
    """Add collections and feature in the STAC catalog for tests.

    Args:
        client (TestClient): The catalog client.
        toto_s1_l1 (Collection): a collection named S1_L1 with the user id toto.
        toto_s2_l3 (Collection): a collection named S2_L3 with the user id toto.
        titi_s2_l1 (Collection): a collection named S2_L1 with the user id titi.
        feature_toto_S1_L1_0 (Feature): a feature from the collection S1_L1 with the
        user id toto.
        feature_toto_S1_L1_1 (Feature): a second feature from the collection S1_L1
        with the user id toto.
        feature_titi_S2_L1_0 (Feature): a feature from the collection S2_L1 with the
        user id titi.
    """
    add_collection(client, toto_s1_l1)
    add_collection(client, toto_s2_l3)
    add_collection(client, titi_s2_l1)
    add_feature(client, feature_toto_S1_L1_0)
    add_feature(client, feature_toto_S1_L1_1)
    add_feature(client, feature_titi_S2_L1_0)


@pytest.mark.integration
class TestRedirectionCatalogUserIdCollections:
    """This class contains integration tests for the endpoint '/catalog/{ownerId}/collections'"""

    def test_status_code_200_toto_if_good_endpoint(self, client):
        response = client.get("/catalog/toto/collections")
        assert response.status_code == 200

    def test_status_code_200_titi_if_good_endpoint(self, client):
        response = client.get("/catalog/titi/collections")
        assert response.status_code == 200

    def load_json_collections(self, client, endpoint):
        response = client.get(endpoint)
        collections = json.loads(response.content)["collections"]
        return {collection["id"] for collection in collections}

    def test_collections_with_toto_removed(self, client, toto_s1_l1, toto_s2_l3, titi_s2_l1):
        collections_ids = self.load_json_collections(client, "/catalog/toto/collections")
        assert collections_ids == {toto_s1_l1.name, toto_s2_l3.name}

    def test_collections_with_titi_removed(self, client, titi_s2_l1):
        collections_ids = self.load_json_collections(client, "catalog/titi/collections")
        assert collections_ids == {titi_s2_l1.name}

    def test_link_parent_is_valid(self, client):
        response = client.get("/catalog/toto/collections")
        response_json = json.loads(response.content)
        links = response_json["links"]
        parent_link = next(link for link in links if link["rel"] == "parent")
        assert parent_link == {
            "rel": "parent",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_link_root_is_valid(self, client):
        response = client.get("/catalog/toto/collections")
        response_json = json.loads(response.content)
        links = response_json["links"]
        root_link = next(link for link in links if link["rel"] == "root")
        assert root_link == {
            "rel": "root",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_link_self_is_valid(self, client):
        response = client.get("/catalog/toto/collections")
        response_json = json.loads(response.content)
        links = response_json["links"]
        self_link = next(link for link in links if link["rel"] == "self")
        assert self_link == {
            "rel": "self",
            "type": "application/json",
            "href": "http://testserver/catalog/toto/collections",
        }

    def test_collection_link_items_is_valid(self, client):
        response = client.get("/catalog/toto/collections")
        response_json = json.loads(response.content)
        collection = response_json["collections"][0]
        collection_id = collection["id"]
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "items")
        assert link == {
            "rel": "items",
            "type": "application/geo+json",
            "href": f"http://testserver/catalog/toto/collections/{collection_id}/items",
        }

    def test_collection_link_parent_is_valid(self, client):
        response = client.get("/catalog/toto/collections")
        response_json = json.loads(response.content)
        collection = response_json["collections"][0]
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "parent")
        assert link == {
            "rel": "parent",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_collection_link_root_is_valid(self, client):
        response = client.get("/catalog/toto/collections")
        response_json = json.loads(response.content)
        collection = response_json["collections"][0]
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "root")
        assert link == {
            "rel": "root",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_collection_link_self_is_valid(self, client):
        response = client.get("/catalog/toto/collections")
        response_json = json.loads(response.content)
        collection = response_json["collections"][0]
        collection_id = collection["id"]
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "self")
        assert link == {
            "rel": "self",
            "type": "application/json",
            "href": f"http://testserver/catalog/toto/collections/{collection_id}",
        }

    def test_collection_link_license_is_valid(self, client):
        response = client.get("/catalog/toto/collections")
        response_json = json.loads(response.content)
        collection = response_json["collections"][0]
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "license")
        assert link == {
            "rel": "license",
            "href": "https://creativecommons.org/licenses/publicdomain/",
            "title": "public domain",
        }

    def test_collection_link_about_is_valid(self, client):
        pass


@pytest.mark.integration
class TestRedirectionCatalogUserIdCollectionsCollectionid:
    """This class contains integration tests for the endpoint '/catalog/{ownerId}/collections/{collectionId}'."""

    def test_status_code_200_toto_if_good_endpoint(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        assert response.status_code == 200

    def test_status_code_200_titi_if_good_endpoint(self, client):
        response = client.get("/catalog/titi/collections/S2_L1")
        assert response.status_code == 200

    def load_json_collection(self, client, endpoint):
        response = client.get(endpoint)
        collection = json.loads(response.content)
        return collection["id"]

    def test_collection_toto_S1_L1_with_toto_removed(self, client, toto_s1_l1, toto_s2_l3, titi_s2_l1):
        collection_id = self.load_json_collection(client, "/catalog/toto/collections/S1_L1")
        assert collection_id == toto_s1_l1.name

    def test_collection_titi_S2_L1_with_titi_removed(self, client, titi_s2_l1):
        collection_id = self.load_json_collection(client, "catalog/titi/collections/S2_L1")
        assert collection_id == titi_s2_l1.name

    def test_collection_toto_S1_L1_link_items_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        collection = json.loads(response.content)
        collection_id = collection["id"]
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "items")
        assert link == {
            "rel": "items",
            "type": "application/geo+json",
            "href": f"http://testserver/catalog/toto/collections/{collection_id}/items",
        }

    def test_collection_toto_S1_L1_link_parent_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "parent")
        assert link == {
            "rel": "parent",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_collection_toto_S1_L1_link_root_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "root")
        assert link == {
            "rel": "root",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_collection_toto_S1_L1_link_self_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        collection = json.loads(response.content)
        collection_id = collection["id"]
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "self")
        assert link == {
            "rel": "self",
            "type": "application/json",
            "href": f"http://testserver/catalog/toto/collections/{collection_id}",
        }

    def test_collection_toto_S1_L1_link_license_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "license")
        assert link == {
            "rel": "license",
            "href": "https://creativecommons.org/licenses/publicdomain/",
            "title": "public domain",
        }


@pytest.mark.integration
class TestRedirectionGetItems:
    """This class contains integration tests for the endpoint '/catalog/{ownerId}/collections/{collectionId}/items'."""

    def test_status_code_200_feature_toto_if_good_endpoint(self, client):
        response = client.get("/catalog/toto/collections/S1_L1/items")
        assert response.status_code == 200

    def test_status_code_200_feature_titi_if_good_endpoint(self, client):
        response = client.get("/catalog/titi/collections/S2_L1/items")
        assert response.status_code == 200

    def load_json_collection(self, client, endpoint):
        response = client.get(endpoint)
        features = json.loads(response.content)["features"]
        return {feature["collection"] for feature in features}

    def test_features_toto_S1_L1_with_toto_removed(self, client, feature_toto_S1_L1_0, feature_toto_S1_L1_1):
        feature_collection = self.load_json_collection(client, "/catalog/toto/collections/S1_L1/items")
        assert feature_collection == {feature_toto_S1_L1_0.collection, feature_toto_S1_L1_1.collection}

    def test_feature_titi_S2_L1_0_with_titi_removed(self, client, feature_titi_S2_L1_0):
        feature_collection = self.load_json_collection(client, "catalog/titi/collections/S2_L1/items")
        assert feature_collection == {feature_titi_S2_L1_0.collection}


from pathlib import Path
from fastapi.openapi.utils import get_openapi
from rs_server_catalog.main import app


def add_parameter_owner_id(parameters: list[dict]) -> dict:
    to_add = {
        "description": "Catalog owner id",
        "required": True,
        "schema": {"type": "string", "title": "Catalog owner id", "description": "Catalog owner id"},
        "name": "owner_id",
        "in": "path",
    }
    parameters.append(to_add)
    return parameters


def test_extract_openapi_specification() -> None:
    """Extract the openapi specification to the given folder.

    Retrieve the openapi specification from the FastAPI instance in json format
    and write it in the given folder in a file named openapi.json.

    :param to_folder: the folder where the specification is written
    :return: None
    """
    to_folder = Path("rs_server_catalog/openapi_specification")
    with open(to_folder / "openapi.json", "w", encoding="utf-8") as f:
        openapi_spec = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            routes=app.routes,
        )
        openapi_spec_paths = openapi_spec["paths"]
        for key, _ in openapi_spec_paths.items():
            new_key = "/catalog/{owner_id}" + key
            openapi_spec_paths[new_key] = openapi_spec_paths.pop(key)
            endpoint = openapi_spec_paths[new_key]
            for method_key, _ in endpoint.items():
                method = endpoint[method_key]
                if "parameters" in method.keys():
                    method["parameters"] = add_parameter_owner_id(method["parameters"])
                else:
                    method["parameters"] = add_parameter_owner_id([])
        json.dump(
            openapi_spec,
            f,
            indent=4,
        )
