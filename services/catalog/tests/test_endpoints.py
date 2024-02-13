import json

import pytest

from tests.conftest import add_collection


@pytest.mark.integration
@pytest.fixture(scope="session", autouse=True)
def setup_database(client, toto_s1_l1, toto_s2_l3, titi_s2_l1):
    add_collection(client, toto_s1_l1)
    add_collection(client, toto_s2_l3)
    add_collection(client, titi_s2_l1)


@pytest.mark.integration
class TestRedirectionCatalogUserIdCollections:
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
        # sourcery skip: class-extract-method
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
