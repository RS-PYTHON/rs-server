"""Integration tests for user_catalog module."""

import json

import pytest

from tests.conftest import add_collection, add_feature


@pytest.mark.integration
class TestRedirectionCatalogUserIdCollections:  # pylint: disable=missing-function-docstring
    """This class contains integration tests for the endpoint '/catalog/{ownerId}/collections'"""

    def test_status_code_200_toto_if_good_endpoint(self, client):
        response = client.get("/catalog/toto/collections")
        assert response.status_code == 200

    def test_status_code_200_titi_if_good_endpoint(self, client):
        response = client.get("/catalog/titi/collections")
        assert response.status_code == 200

    def test_status_code_200_post_new_collection_esmeralda_s1_l1(self, client):
        new_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
        }
        response = client.post("/catalog/esmeralda/collections", json=new_collection)
        assert response.status_code == 200

    def test_status_code_200_update_collection_esmeralda_s1_l1(self, client):
        esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
        }
        client.post("/catalog/esmeralda/collections", json=esmeralda_collection)
        new_esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for BIG Esmeralda user.",
            "stac_version": "1.0.0",
        }
        response = client.put("/catalog/esmeralda/collections", json=new_esmeralda_collection)
        assert response.status_code == 200

    def test_if_update_collection_esmeralda_s1_l1_worked(self, client):
        esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
        }
        client.post("/catalog/esmeralda/collections", json=esmeralda_collection)
        new_esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for BIG Esmeralda user.",
            "stac_version": "1.0.0",
        }
        client.put("/catalog/esmeralda/collections", json=new_esmeralda_collection)
        response = client.get("/catalog/esmeralda/collections/S1_L1")
        content = json.loads(response.content)
        assert content["description"] == "The S1_L1 collection for BIG Esmeralda user."

    def test_collection_with_esmeralda_added_after_post(self, client):
        new_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
        }
        client.post("/catalog/esmeralda/collections", json=new_collection)
        response = client.get("/catalog/esmeralda/collections/S1_L1")
        assert response.status_code == 200

    def load_json_collections(self, client, endpoint):
        response = client.get(endpoint)
        collections = json.loads(response.content)["collections"]
        return {collection["id"] for collection in collections}

    def test_collections_with_toto_removed(self, client, toto_s1_l1, toto_s2_l3):
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
class TestRedirectionCatalogUserIdCollectionsCollectionid:  # pylint: disable=missing-function-docstring
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

    def test_collection_toto_s1_l1_with_toto_removed(self, client, toto_s1_l1):
        collection_id = self.load_json_collection(client, "/catalog/toto/collections/S1_L1")
        assert collection_id == toto_s1_l1.name

    def test_collection_titi_s2_l1_with_titi_removed(self, client, titi_s2_l1):
        collection_id = self.load_json_collection(client, "catalog/titi/collections/S2_L1")
        assert collection_id == titi_s2_l1.name

    def test_collection_toto_s1_l1_link_items_is_valid(self, client):
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

    def test_collection_toto_s1_l1_link_parent_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "parent")
        assert link == {
            "rel": "parent",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_collection_toto_s1_l1_link_root_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "root")
        assert link == {
            "rel": "root",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_collection_toto_s1_l1_link_self_is_valid(self, client):
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

    def test_collection_toto_s1_l1_link_license_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "license")
        assert link == {
            "rel": "license",
            "href": "https://creativecommons.org/licenses/publicdomain/",
            "title": "public domain",
        }

    def test_delete_collection(self, client, toto_s1_l1, feature_toto_s1_l1_0, feature_toto_s1_l1_1):
        response = client.delete("/catalog/toto/collections/S1_L1")
        add_collection(client, toto_s1_l1)
        add_feature(client, feature_toto_s1_l1_0)
        add_feature(client, feature_toto_s1_l1_1)
        assert response.status_code == 200

    # def test_update_collection(self, client):
    #     toto_s1_l1 = client.get("/catalog/toto/collections/S1_L1")
    #     json_toto = json.loads(toto_s1_l1.content)
    #     response = client.put("/catalog/toto/collections/S1_L1", json=json_toto, headers=toto_s1_l1.headers)
    #     assert response.status_code == 200


@pytest.mark.integration
class TestRedirectionItems:  # pylint: disable=missing-function-docstring
    """This class contains integration tests for the endpoint '/catalog/{ownerId}/collections/{collectionId}/items'."""

    def test_status_code_200_feature_toto_if_good_endpoint(self, client):
        response = client.get("/catalog/toto/collections/S1_L1/items")
        assert response.status_code == 200

    def test_status_code_200_feature_titi_if_good_endpoint(self, client):
        response = client.get("/catalog/titi/collections/S2_L1/items")
        assert response.status_code == 200

    def test_status_code_200_post_new_feature_esmeralda(self, client):
        esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
        }

        client.post("/catalog/esmeralda/collections", json=esmeralda_collection)

        new_feature = {
            "id": "feature_0",
            "bbox": [-94.6334839, 37.0332547, -94.6005249, 37.0595608],
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-94.6334839, 37.0595608],
                        [-94.6334839, 37.0332547],
                        [-94.6005249, 37.0332547],
                        [-94.6005249, 37.0595608],
                        [-94.6334839, 37.0595608],
                    ],
                ],
            },
            "collection": "S1_L1",
            "properties": {
                "gsd": 0.5971642834779395,
                "width": 2500,
                "height": 2500,
                "datetime": "2000-02-02T00:00:00Z",
                "proj:epsg": 3857,
                "orientation": "nadir",
            },
        }
        response = client.post("/catalog/esmeralda/collections/S1_L1/items", json=new_feature)
        assert response.status_code == 200

    def test_feature_with_esmeralda_added_after_post(self, client):
        esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
        }

        client.post("/catalog/esmeralda/collections", json=esmeralda_collection)

        new_feature = {
            "id": "feature_0",
            "bbox": [-94.6334839, 37.0332547, -94.6005249, 37.0595608],
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-94.6334839, 37.0595608],
                        [-94.6334839, 37.0332547],
                        [-94.6005249, 37.0332547],
                        [-94.6005249, 37.0595608],
                        [-94.6334839, 37.0595608],
                    ],
                ],
            },
            "collection": "S1_L1",
            "properties": {
                "gsd": 0.5971642834779395,
                "width": 2500,
                "height": 2500,
                "datetime": "2000-02-02T00:00:00Z",
                "proj:epsg": 3857,
                "orientation": "nadir",
            },
        }
        client.post("/catalog/esmeralda/collections/S1_L1/items", json=new_feature)
        response = client.get("/catalog/esmeralda/collections/S1_L1/items/feature_0")
        assert response.status_code == 200

    def load_json_feature(self, client, endpoint):
        response = client.get(endpoint)
        features = json.loads(response.content)["features"]
        return {feature["collection"] for feature in features}

    def test_features_toto_s1_l1_with_toto_removed(self, client, feature_toto_s1_l1_0, feature_toto_s1_l1_1):
        feature_collection = self.load_json_feature(client, "/catalog/toto/collections/S1_L1/items")
        assert feature_collection == {feature_toto_s1_l1_0.collection, feature_toto_s1_l1_1.collection}

    def test_feature_titi_s2_l1_0_with_titi_removed(self, client, feature_titi_s2_l1_0):
        feature_collection = self.load_json_feature(client, "catalog/titi/collections/S2_L1/items")
        assert feature_collection == {feature_titi_s2_l1_0.collection}

    def test_link_collection_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1/items")
        response_json = json.loads(response.content)
        links = response_json["links"]
        self_link = next(link for link in links if link["rel"] == "collection")
        assert self_link == {
            "rel": "collection",
            "type": "application/json",
            "href": "http://testserver/catalog/toto/collections/S1_L1",
        }


class TestRedirectionItemsItemId:  # pylint: disable=missing-function-docstring
    """This class contains integration tests for the endpoint '/catalog/{ownerId}/collections/{collectionId}/items/{item_id}'."""

    def test_status_code_200_feature_toto_if_good_endpoint(self, client):
        response = client.get("/catalog/toto/collections/S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        assert response.status_code == 200

    def test_status_code_200_feature_titi_if_good_endpoint(self, client):
        response = client.get("/catalog/titi/collections/S2_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        assert response.status_code == 200

    def load_json_feature(self, client, endpoint):
        response = client.get(endpoint)
        feature = json.loads(response.content)
        return feature["collection"]

    def test_feature_toto_s1_l1_0_with_toto_removed(self, client, feature_toto_s1_l1_0):
        feature_id = self.load_json_feature(
            client,
            "/catalog/toto/collections/S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
        )
        assert feature_id == feature_toto_s1_l1_0.collection

    def test_collection_titi_s2_l1_with_titi_removed(self, client, feature_titi_s2_l1_0):
        feature_id = self.load_json_feature(
            client,
            "/catalog/titi/collections/S2_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
        )
        assert feature_id == feature_titi_s2_l1_0.collection

    def test_update_feature(self, client):
        toto_s1_l1_feature = client.get("/catalog/toto/collections/S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        json_toto = json.loads(toto_s1_l1_feature.content)
        response = client.put(
            "/catalog/toto/collections/S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
            json=json_toto,
            headers=toto_s1_l1_feature.headers,
        )
        assert response.status_code == 200

    def test_delete_feature(self, client, feature_toto_s1_l1_0):
        response = client.delete("/catalog/toto/collections/S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        add_feature(client, feature_toto_s1_l1_0)
        assert response.status_code == 200


def test_status_code_200_docs_if_good_endpoints(client):  # pylint: disable=missing-function-docstring
    response = client.get("/api.html")
    assert response.status_code == 200


def test_status_code_200_search_if_good_endpoint(client):  # pylint: disable=missing-function-docstring
    response = client.get("/catalog/search")
    assert response.status_code == 200
