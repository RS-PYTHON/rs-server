"""Integration tests for user_catalog module."""

import json

import pytest


@pytest.mark.integration
class TestRedirectionCatalogUserIdCollections:  # pylint: disable=missing-function-docstring
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


@pytest.mark.integration
class TestRedirectionGetItems:  # pylint: disable=missing-function-docstring
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

    def test_features_toto_s1_l1_with_toto_removed(self, client, feature_toto_s1_l1_0, feature_toto_s1_l1_1):
        feature_collection = self.load_json_collection(client, "/catalog/toto/collections/S1_L1/items")
        assert feature_collection == {feature_toto_s1_l1_0.collection, feature_toto_s1_l1_1.collection}

    def test_feature_titi_s2_l1_0_with_titi_removed(self, client, feature_titi_s2_l1_0):
        feature_collection = self.load_json_collection(client, "catalog/titi/collections/S2_L1/items")
        assert feature_collection == {feature_titi_s2_l1_0.collection}


def test_status_code_200_docs_if_good_endpoints(client):  # pylint: disable=missing-function-docstring
    response = client.get("/api.html")
    assert response.status_code == 200


@pytest.mark.unit
@pytest.mark.parametrize(
    "owner, collection_id, feature_data",
    [
        (
            "darius",
            "S1_L2",
            {
                "collection": "S1_L2",
                "assets": {
                    "zarr": {
                        "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                        "roles": ["data"],
                    },
                    "cog": {
                        "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                        "roles": ["data"],
                    },
                    "ncdf": {"href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T902.nc", "roles": ["data"]},
                },
                "bbox": [0],
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
                "id": "S1SIWOCN_20220412T054447_0024_S139",
                "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
                "other_metadata": {},
                "properties": {
                    "gsd": 0.5971642834779395,
                    "width": 2500,
                    "height": 2500,
                    "datetime": "2000-02-02T00:00:00Z",
                    "proj:epsg": 3857,
                    "orientation": "nadir",
                },
                "stac_extensions": [
                    "https://stac-extensions.github.io/eopf/v1.0.0/schema.json",
                    "https://stac-extensions.github.io/eo/v1.1.0/schema.json",
                    "https://stac-extensions.github.io/sat/v1.0.0/schema.json",
                    "https://stac-extensions.github.io/view/v1.0.0/schema.json",
                    "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
                    "https://stac-extensions.github.io/processing/v1.1.0/schema.json",
                ],
                "stac_version": "1.0.0",
                "type": "Feature",
            },
        ),
    ],
)
def test_publish_item_update(client, owner, collection_id, feature_data):
    # Check if that user darius have a collection (Added in conftest -> setup_database)
    # Add a featureCollection to darius collection
    added_feature = client.post(f"/catalog/{owner}/collections/{collection_id}/items", json=feature_data)
    assert added_feature.status_code == 200
    feature_data = json.loads(added_feature.content)
    # check if owner was added and match to the owner of the collection
    assert feature_data["owner"] == owner
    # check if stac_extension correctly updated collection name
    assert feature_data["collection"] == f"{owner}_{collection_id}"
    # check if stac extension was added
    assert "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json" in feature_data["stac_extensions"]

    # More test to be added here when bucket move is implemented.
