"""Integration tests for user_catalog module."""

import json
import os
import os.path as osp
import pathlib

import fastapi
import pytest
import requests
import yaml
from moto.server import ThreadedMotoServer
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler

from .conftest import add_collection, add_feature  # pylint: disable=no-name-in-module

# Resource folders specified from the parent directory of this current script
S3_RSC_FOLDER = osp.realpath(osp.join(osp.dirname(__file__), "resources", "s3"))


# Moved here, since this functions utility not fixtures.
def export_aws_credentials():
    """Export AWS credentials as environment variables for testing purposes.

    This function sets the following environment variables with dummy values for AWS credentials:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_SECURITY_TOKEN
    - AWS_SESSION_TOKEN
    - AWS_DEFAULT_REGION

    Note: This function is intended for testing purposes only, and it should not be used in production.

    Returns:
        None

    Raises:
        None
    """
    with open(osp.join(S3_RSC_FOLDER, "s3.yml"), "r", encoding="utf-8") as f:
        s3_config = yaml.safe_load(f)
        os.environ.update(s3_config["s3"])
        os.environ.update(s3_config["boto"])


def clear_aws_credentials():
    """Clear AWS credentials from environment variables."""
    with open(osp.join(S3_RSC_FOLDER, "s3.yml"), "r", encoding="utf-8") as f:
        s3_config = yaml.safe_load(f)
        for env_var in list(s3_config["s3"].keys()) + list(s3_config["boto"].keys()):
            del os.environ[env_var]


@pytest.mark.integration
class TestRedirectionCatalogUserIdCollections:  # pylint: disable=missing-function-docstring
    """This class contains integration tests for the endpoint '/catalog/{ownerId}/collections'"""

    def test_status_code_200_toto_if_good_endpoint(self, client):
        test_params = {"filter-lang": "cql2-text", "filter": "owner_id='toto'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200

    def test_status_code_200_titi_if_good_endpoint(self, client):
        test_params = {"filter-lang": "cql2-text", "filter": "owner_id='titi'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200

    def test_status_code_200_post_new_collection_esmeralda_s1_l1(self, client):
        new_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
            "owner": "esmeralda",
        }
        response = client.post("/catalog/collections", json=new_collection)
        assert response.status_code == 200
        client.delete("/catalog/esmeralda/collections/S1_L1")

    def test_status_code_200_update_collection_esmeralda_s1_l1(self, client):
        esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
            "owner": "esmeralda",
        }
        client.post("/catalog/collections", json=esmeralda_collection)
        new_esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for New Esmeralda user.",
            "stac_version": "1.0.0",
            "owner": "esmeralda",
        }
        response = client.put("/catalog/collections", json=new_esmeralda_collection)
        assert response.status_code == 200
        response_json = json.loads(response.content)
        assert response_json["id"] == "S1_L1"
        client.delete("/catalog/esmeralda/collections/S1_L1")

    def test_if_update_collection_esmeralda_s1_l1_worked(self, client):
        esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
            "owner": "esmeralda",
        }
        client.post("/catalog/collections", json=esmeralda_collection)
        new_esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for BIG Esmeralda user.",
            "stac_version": "1.0.0",
            "owner": "esmeralda",
        }
        client.put("/catalog/esmeralda/collections", json=new_esmeralda_collection)
        response = client.get("/catalog/esmeralda/collections/S1_L1")
        content = json.loads(response.content)
        assert content["description"] == "The S1_L1 collection for BIG Esmeralda user."
        client.delete("/catalog/esmeralda/collections/S1_L1")

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
        client.delete("/catalog/esmeralda/collections/S1_L1")

    def load_json_collections(self, client, endpoint, owner):
        response = client.get(endpoint, params={"owner": owner})
        collections = json.loads(response.content)["collections"]
        return {collection["id"] for collection in collections}

    def test_collections_with_toto_removed(self, client, toto_s1_l1, toto_s2_l3):
        collections_ids = self.load_json_collections(client, "/catalog/collections", "toto")
        assert collections_ids == {toto_s1_l1.name, toto_s2_l3.name}

    def test_collections_with_titi_removed(self, client, titi_s2_l1):
        collections_ids = self.load_json_collections(client, "catalog/collections", "titi")
        assert collections_ids == {titi_s2_l1.name}

    def test_link_parent_is_valid(self, client):
        response = client.get("/catalog/collections", params={"owner": "toto"})
        response_json = json.loads(response.content)
        links = response_json["links"]
        parent_link = next(link for link in links if link["rel"] == "parent")
        assert parent_link == {
            "rel": "parent",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_link_root_is_valid(self, client):
        response = client.get("/catalog/collections", params={"owner": "toto"})
        response_json = json.loads(response.content)
        links = response_json["links"]
        root_link = next(link for link in links if link["rel"] == "root")
        assert root_link == {
            "rel": "root",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_link_self_is_valid(self, client):
        response = client.get("/catalog/collections", params={"owner": "toto"})
        response_json = json.loads(response.content)
        links = response_json["links"]
        self_link = next(link for link in links if link["rel"] == "self")
        assert self_link == {
            "rel": "self",
            "type": "application/json",
            "href": "http://testserver/catalog/toto/collections",
        }

    def test_collection_link_items_is_valid(self, client):
        response = client.get("/catalog/collections", params={"owner": "toto"})
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
        response = client.get("/catalog/collections", params={"owner": "toto"})
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
        response = client.get("/catalog/collections", params={"owner": "toto"})
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
        response = client.get("/catalog/collections", params={"owner": "toto"})
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
        response = client.get("/catalog/collections", params={"owner": "toto"})
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
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "owner_id='toto'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200

    def test_status_code_200_titi_if_good_endpoint(self, client):
        test_params = {"collections": "S2_L1", "filter-lang": "cql2-text", "filter": "owner_id='titi'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200

    def load_json_collection(self, client, endpoint, params):
        response = client.get(endpoint, params=params)
        collection = json.loads(response.content)
        return collection["id"]

    def test_collection_toto_s1_l1_with_toto_removed(self, client, toto_s1_l1):
        test_params = {"collections": "S1_L1", "filter": "owner_id='toto'"}
        collection_id = self.load_json_collection(client, "/catalog/search", params=test_params)
        assert collection_id == toto_s1_l1.name

    def test_collection_titi_s2_l1_with_titi_removed(self, client, titi_s2_l1):
        test_params = {"collections": "S2_L1", "filter": "owner_id='titi'"}
        collection_id = self.load_json_collection(client, "catalog/search", params=test_params)
        assert collection_id == titi_s2_l1.name

    def test_collection_toto_s1_l1_link_items_is_valid(self, client):
        test_params = {"collections": "S1_L1", "filter": "owner_id='toto'"}
        response = client.get("catalog/search", params=test_params)
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
        response = client.get("/catalog/collections/toto:S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "parent")
        assert link == {
            "rel": "parent",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_collection_toto_s1_l1_link_root_is_valid(self, client):
        response = client.get("/catalog/collections/toto:S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "root")
        assert link == {
            "rel": "root",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_collection_toto_s1_l1_link_self_is_valid(self, client):
        response = client.get("/catalog/collections/toto:S1_L1")
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
        response = client.get("/catalog/collections/toto:S1_L1")
        collection = json.loads(response.content)
        links = collection["links"]
        link = next(link for link in links if link["rel"] == "license")
        assert link == {
            "rel": "license",
            "href": "https://creativecommons.org/licenses/publicdomain/",
            "title": "public domain",
        }

    def test_delete_collection(self, client, toto_s1_l1, feature_toto_s1_l1_0, feature_toto_s1_l1_1):
        response = client.delete("/catalog/collections/toto:S1_L1")
        add_collection(client, toto_s1_l1)
        add_feature(client, feature_toto_s1_l1_0)
        add_feature(client, feature_toto_s1_l1_1)
        assert response.status_code == 200


@pytest.mark.integration
class TestRedirectionItems:  # pylint: disable=missing-function-docstring
    """This class contains integration tests for the endpoint '/catalog/{ownerId}/collections/{collectionId}/items'."""

    def test_status_code_200_feature_toto_if_good_endpoint(self, client):
        response = client.get("/catalog/collections/toto:S1_L1/items")
        assert response.status_code == 200

    def test_status_code_200_feature_titi_if_good_endpoint(self, client):
        response = client.get("/catalog/collections/titi:S2_L1/items")
        assert response.status_code == 200

    def test_status_code_200_post_new_feature_esmeralda(self, client):
        esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
            "owner": "esmeralda",
        }

        client.post("/catalog/collections", json=esmeralda_collection)

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
            "assets": {},
            "stac_extensions": [],
        }
        response = client.post("/catalog/collections/esmeralda:S1_L1/items", json=new_feature)
        assert response.status_code == 200
        client.delete("/catalog/esmeralda/collections/S1_L1")

    def test_feature_with_esmeralda_added_after_post(self, client):
        esmeralda_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "description": "The S1_L1 collection for Esmeralda user.",
            "stac_version": "1.0.0",
            "owner": "esmeralda",
        }

        client.post("/catalog/collections", json=esmeralda_collection)

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
            "assets": {},
            "stac_extensions": [],
        }
        client.post("/catalog/esmeralda/collections/S1_L1/items", json=new_feature)
        response = client.get("/catalog/esmeralda/collections/S1_L1/items/feature_0")
        assert response.status_code == 200
        client.delete("/catalog/esmeralda/collections/S1_L1")

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
        collection_link = next(link for link in links if link["rel"] == "collection")
        assert collection_link == {
            "rel": "collection",
            "type": "application/json",
            "href": "http://testserver/catalog/toto/collections/S1_L1",
        }

    def test_link_parent_is_valid(self, client):
        response = client.get("/catalog/toto/collections/S1_L1/items")
        response_json = json.loads(response.content)
        links = response_json["links"]
        parent_link = next(link for link in links if link["rel"] == "parent")
        assert parent_link == {
            "rel": "parent",
            "type": "application/json",
            "href": "http://testserver/catalog/toto/collections/S1_L1",
        }

    def test_link_root_is_valid(self, client):
        response = client.get("/catalog/collections/toto:S1_L1/items")
        response_json = json.loads(response.content)
        links = response_json["links"]
        root_link = next(link for link in links if link["rel"] == "root")
        assert root_link == {
            "rel": "root",
            "type": "application/json",
            "href": "http://testserver/catalog/toto",
        }

    def test_link_self_is_valid(self, client):
        response = client.get("/catalog/collections/toto:S1_L1/items")
        response_json = json.loads(response.content)
        links = response_json["links"]
        self_link = next(link for link in links if link["rel"] == "self")
        assert self_link == {
            "rel": "self",
            "type": "application/geo+json",
            "href": "http://testserver/collections/toto_S1_L1/items",
        }


class TestRedirectionItemsItemId:  # pylint: disable=missing-function-docstring
    """This class contains integration tests for the endpoint
    '/catalog/{ownerId}/collections/{collectionId}/items/{item_id}'."""

    def test_status_code_200_feature_toto_if_good_endpoint(self, client):
        response = client.get("/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        assert response.status_code == 200

    def test_status_code_200_feature_titi_if_good_endpoint(self, client):
        response = client.get("/catalog/collections/titi:S2_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        assert response.status_code == 200

    def load_json_feature(self, client, endpoint):
        response = client.get(endpoint)
        feature = json.loads(response.content)
        return feature["collection"]

    def test_feature_toto_s1_l1_0_with_toto_removed(self, client, feature_toto_s1_l1_0):
        feature_id = self.load_json_feature(
            client,
            "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
        )
        assert feature_id == feature_toto_s1_l1_0.collection

    def test_collection_titi_s2_l1_with_titi_removed(self, client, feature_titi_s2_l1_0):
        feature_id = self.load_json_feature(
            client,
            "/catalog/collections/titi:S2_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
        )
        assert feature_id == feature_titi_s2_l1_0.collection

    def test_update_feature(self, client):
        toto_s1_l1_feature = client.get("/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        json_toto = json.loads(toto_s1_l1_feature.content)
        response = client.put(
            "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
            json=json_toto,
            headers=toto_s1_l1_feature.headers,
        )
        assert response.status_code == 200
        response_json = json.loads(response.content)
        assert response_json["collection"] == "S1_L1"

    def test_delete_feature(self, client, feature_toto_s1_l1_0):
        response = client.delete("/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        add_feature(client, feature_toto_s1_l1_0)
        assert response.status_code == 200

    def test_self_link_is_valid(self, client):
        response = client.get("/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d")
        response_json = json.loads(response.content)
        links = response_json["links"]
        self_link = next(link for link in links if link["rel"] == "self")
        assert self_link == {
            "rel": "self",
            "type": "application/geo+json",
            "href": "http://testserver/catalog/toto/collections/S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
        }


def test_status_code_200_docs_if_good_endpoints(client):  # pylint: disable=missing-function-docstring
    response = client.get("/api.html")
    assert response.status_code == 200


class TestCatalogSearchEndpoint:
    """This class contains integration tests for the endpoint '/catalog/search'."""

    def test_search_endpoint_with_filter_owner_id_and_other(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500 AND owner_id='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 2

        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=3000 AND owner_id='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 0

    def test_search_endpoint_with_filter_owner_id_only(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "owner_id='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 2

    def test_search_endpoint_without_collections(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"filter-lang": "cql2-text", "filter": "owner_id='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 2

    def test_searh_endpoint_without_owner_id(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 0  # behavior to be determined

    def test_search_endpoint_with_specific_filter(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 0  # behavior to be determined

    def test_search_endpoint_without_filter_lang(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "filter": "width=3000 AND owner_id='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 0  # behavior to be determined

    def test_post_search_endpoint(self, client):  # pylint: disable=missing-function-docstring
        test_json = {
            "collections": "S1_L1",
            "filter-lang": "cql2-json",
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "owner_id"}, "toto"]},
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                ],
            },
        }

        response = client.post("/catalog/search", json=test_json)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 2

    def test_queryables(self, client):  # pylint: disable=missing-function-docstring
        try:
            response = client.get("/catalog/queryables")
            content = json.loads(response.content)
            with open("queryables.json", "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2)
            assert response.status_code == 200
        finally:
            pathlib.Path("queryables.json").unlink(missing_ok=True)


# REWORKED TESTS
class TestCatalogPublishCollectionEndpoint:
    def test_create_new_minimal_collection(self, client):
        """
        Test endpoint POST /catalog/collections.
        """
        minimal_collection = {
            "id": "test_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "test_owner",
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        # Check that collection status code is 200
        assert response.status_code == fastapi.status.HTTP_200_OK
        # Check that internal collection id is set to owner_collection
        assert json.loads(response.content)["id"] == "test_collection"
        assert json.loads(response.content)["owner"] == "test_owner"

        # # Call search endpoint to verify presence of collection in catalog
        # test_params = {"collections": "test_collection", "filter-lang": "cql2-text", "filter": "owner='test_owner'"}
        # response = client.get("/catalog/search", params=test_params)
        # assert response.status_code == 200

        # Test that /catalog/collection GET endpoint returns the correct collection id
        response = client.get("/catalog/collections", params={"owner": "test_owner"})
        assert response.status_code == fastapi.status.HTTP_200_OK
        response_content = json.loads(response.content)["collections"][0]
        # Check that values are correctly written in catalogDB
        assert response_content["id"] == minimal_collection["id"]
        assert response_content["owner"] == minimal_collection["owner"]
        assert response_content["description"] == minimal_collection["description"]
        assert response_content["type"] == minimal_collection["type"]
        assert response_content["stac_version"] == minimal_collection["stac_version"]

    def test_failure_to_create_collection(self, client):
        """
        Test endpoint POST /catalog/collections with incorrect collection.
        Endpoint: POST /catalog/collections
        """
        # This minimal collection is missing the id field
        minimal_incorrect_collection = {
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "test_incorrect_owner",
        }
        # Test that response is 400 BAD Request
        with pytest.raises(fastapi.HTTPException):
            response = client.post("/catalog/collections", json=minimal_incorrect_collection)
            assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
        # Check that owner from this collection is not written in catalogDB
        response = client.get("/catalog/collections", params={"owner": "test_incorrect_owner"})
        assert not len(json.loads(response.content)["collections"])

    def test_create_a_collection_already_created(self, client):
        """
        Test that endpoint POST /catalog/collections returns 409 Conflict if collection already exists.
        This action can be performed only by PUT or PATCH /catalog/collections.
        """
        minimal_collection = {
            "id": "duplicate_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "duplicate_owner",
        }
        # Test that collection is correctly published
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_200_OK
        # Test that duplicate collection cannot be published
        with pytest.raises(fastapi.HTTPException):
            response = client.post("/catalog/collections", json=minimal_collection)
            assert response.status_code == fastapi.status.HTTP_409_CONFLICT
        # Change values from collection, try to publish again
        minimal_collection["description"] = "test_description_updated"
        with pytest.raises(fastapi.HTTPException):
            response = client.post("/catalog/collections", json=minimal_collection)
            # Test that is not allowed
            assert response.status_code == fastapi.status.HTTP_409_CONFLICT
        # Check into catalogDB that values are not updated
        response = client.get("/catalog/collections", params={"owner": "duplicate_owner"})
        response_content = json.loads(response.content)["collections"][0]
        assert response_content["description"] == "test_description"

    def test_update_a_created_collection(self, client):
        """
        Test that endpoint PUT /catalog/collections updates a collection.
        Endpoint: PUT /catalog/collections.
        """
        minimal_collection = {
            "id": "second_test_collection",
            "type": "Collection",
            "description": "not_updated_test_description",
            "stac_version": "1.0.0",
            "owner": "second_test_owner",
        }
        # Post the collection
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_200_OK
        # test if is ok written in catalogDB
        response = client.get("/catalog/collections", params={"owner": "second_test_owner"})
        response_content = json.loads(response.content)["collections"][0]
        assert response_content["description"] == "not_updated_test_description"
        # Update the collection description and PUT
        minimal_collection["description"] = "the_updated_test_description"
        response = client.put("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_200_OK
        # !!!!! DISABLED, to be added
        # response = client.put("/catalog/collections/second_test_owner/second_test_collection", json=minimal_collection)
        # assert response.status_code == fastapi.status.HTTP_200_OK
        # !!!!
        # Check that collection is correctly updated
        response = client.get("/catalog/collections", params={"owner": "second_test_owner"})
        response_content = json.loads(response.content)["collections"][0]
        assert response_content["description"] == "the_updated_test_description"

    def test_delete_a_created_collection(self, client):
        """
        Test that a created collection can be deleted
        Endpoint: DELETE /catalog/collections.
        """
        minimal_collection = {
            "id": "will_be_deleted_collection",
            "type": "Collection",
            "description": "will_be_deleted_description",
            "stac_version": "1.0.0",
            "owner": "will_be_deleted_owner",
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_200_OK

        # Check that collection is correctly published
        # response = client.get("/catalog/collections", params={"owner": "will_be_deleted_owner"})
        # response_content = json.loads(response.content)['collections'][0]
        # assert response_content['description'] == minimal_collection['description']
        response = client.get("/catalog/collections/will_be_deleted_owner:will_be_deleted_collection/items")

        # # Delete the collection
        # delete_info = {"owner": "will_be_deleted_owner", "id": "will_be_deleted_collection"}
        # response = client.delete("/catalog/collections", params=delete_info)
        # assert response.status_code == fastapi.status.HTTP_200_OK
        # # Check that collection is correctly deleted
        # response = client.get("/catalog/collections", params={"owner": "will_be_deleted_owner"})
        # response_content = json.loads(response.content)['collections'][0]
        # assert response_content['description'] == minimal_collection['description']

    def test_delete_a_non_existent_collection(self, client):
        # Should call delete endpoint on a non existent collection id
        pass


class TestCatalogPublishFeatureWithBucketTransferEndpoint:
    @pytest.mark.parametrize(
        "owner, collection_id",
        [
            (
                "darius",
                "S1_L2",
            ),
        ],
    )
    def test_publish_item_update(self, client, a_correct_feature, owner, collection_id):
        """Test used to verify publication of a featureCollection to the catalog."""
        # Create moto server and temp / catalog bucket
        moto_endpoint = "http://localhost:8077"
        export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        # Enable bucket transfer
        os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"
        server = ThreadedMotoServer(port=8077)
        server.start()
        try:
            s3_handler = S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )

            temp_bucket = "temp-bucket"
            catalog_bucket = "catalog-bucket"
            s3_handler.s3_client.create_bucket(Bucket=temp_bucket)
            s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)
            assert not s3_handler.list_s3_files_obj(temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(catalog_bucket, "")

            # Populate temp-bucket with some small files.
            lst_with_files_to_be_copied = [
                "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T902.nc",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=temp_bucket, Key=obj, Body="testing\n")

            # check that temp_bucket is not empty
            assert s3_handler.list_s3_files_obj(temp_bucket, "")
            # check if temp_bucket content is different from catalog_bucket
            assert sorted(s3_handler.list_s3_files_obj(temp_bucket, "")) != sorted(
                s3_handler.list_s3_files_obj(catalog_bucket, ""),
            )

            # TC01: Add on Sentinel-1 item to the Catalog with a well-formatted STAC JSON file
            # and a good OBS path. => 200 OK
            # Check if that user darius have a collection (Added in conftest -> setup_database)
            # Add a featureCollection to darius collection
            added_feature = client.post(f"/catalog/collections/{owner}:{collection_id}/items", json=a_correct_feature)
            assert added_feature.status_code == 200
            feature_data = json.loads(added_feature.content)
            # check if owner was added and match to the owner of the collection
            assert feature_data["properties"]["owner"] == owner
            # check if stac_extension correctly updated collection name
            assert feature_data["collection"] == f"{owner}_{collection_id}"
            # check if stac extension was added
            assert (
                "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json"
                in feature_data["stac_extensions"]
            )

            # Files were moved, check that catalog_bucket is not empty
            assert s3_handler.list_s3_files_obj(catalog_bucket, "")
            # Check if temp_bucket is now empty
            assert not s3_handler.list_s3_files_obj(temp_bucket, "")
            # Check if buckets content is different
            assert s3_handler.list_s3_files_obj(temp_bucket, "") != s3_handler.list_s3_files_obj(catalog_bucket, "")
            # Check if catalog bucket content match the initial temp-bucket content
            # If so, files were correctly moved from temp-catalog to bucket catalog.
            assert sorted(s3_handler.list_s3_files_obj(catalog_bucket, "")) == sorted(lst_with_files_to_be_copied)
            # clean up
            s3_handler.delete_bucket_completely(temp_bucket)
            s3_handler.delete_bucket_completely(catalog_bucket)

        finally:
            server.stop()
            clear_aws_credentials()
            os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "owner, collection_id",
        [
            (
                "darius",
                "S1_L2",
            ),
        ],
    )
    def test_incorrect_feature_publish(self, client, a_incorrect_feature, owner, collection_id):
        """This test send a featureCollection to the catalog with a wrong format."""
        # TC02: Add on Sentinel-1 item to the Catalog with a wrong-formatted STAC JSON file. => 400 Bad Request
        with pytest.raises(fastapi.HTTPException):
            added_feature = client.post(f"/catalog/collections/{owner}:{collection_id}/items", json=a_incorrect_feature)
            # Bad request = 400
            assert added_feature.status_code == 400

    @pytest.mark.unit
    def test_incorrect_bucket_publish(self, client, a_correct_feature):
        """Test used to verify failure when obs path is wrong."""
        # TC03: Add on Sentinel-1 item to the Catalog with a wrong OBS path  => ERROR => 400 Bad Request
        export_aws_credentials()
        a_correct_feature["assets"]["zarr"]["href"] = "incorrect_s3_url/some_file.zarr.zip"
        a_correct_feature["assets"]["cog"]["href"] = "incorrect_s3_url/some_file.cog.zip"
        a_correct_feature["assets"]["ncdf"]["href"] = "incorrect_s3_url/some_file.ncdf.zip"
        with pytest.raises(fastapi.HTTPException):
            added_feature = client.post("/catalog/collections/darius:S1_L2/items", json=a_correct_feature)
            assert added_feature.status_code == 400
            assert added_feature.content == b'"Invalid obs bucket"'
            clear_aws_credentials()

    @pytest.mark.unit
    def test_custom_bucket_publish(self, client, a_correct_feature):
        """Test with other temp bucket name."""
        moto_endpoint = "http://localhost:8077"
        export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )
        os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"
        server = ThreadedMotoServer(port=8077)
        server.start()
        try:
            custom_bucket = "some-custom-bucket"
            catalog_bucket = "catalog-bucket"
            a_correct_feature["assets"]["zarr"]["href"] = f"s3://{custom_bucket}/correct_location/some_file.zarr.zip"
            a_correct_feature["assets"]["cog"]["href"] = f"s3://{custom_bucket}/correct_location/some_file.cog.zip"
            a_correct_feature["assets"]["ncdf"]["href"] = f"s3://{custom_bucket}/correct_location/some_file.ncdf.zip"
            a_correct_feature["id"] = "new_feature_id"

            s3_handler.s3_client.create_bucket(Bucket=custom_bucket)
            s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)
            lst_with_files_to_be_copied = [
                "correct_location/some_file.zarr.zip",
                "correct_location/some_file.cog.zip",
                "correct_location/some_file.ncdf.zip",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=custom_bucket, Key=obj, Body="testing\n")

            assert s3_handler.list_s3_files_obj(custom_bucket, "")
            assert not s3_handler.list_s3_files_obj(catalog_bucket, "")

            added_feature = client.post("/catalog/collections/darius:S1_L2/items", json=a_correct_feature)
            assert added_feature.status_code == 200

            assert not s3_handler.list_s3_files_obj(custom_bucket, "")
            assert s3_handler.list_s3_files_obj(catalog_bucket, "")

            s3_handler.delete_bucket_completely(custom_bucket)
            s3_handler.delete_bucket_completely(catalog_bucket)

        finally:
            server.stop()
            clear_aws_credentials()
            os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"

    def test_generate_download_presigned_url(self, client):
        """Test used to verify the generation of a presigned url for a download."""
        # Start moto server
        moto_endpoint = "http://localhost:8077"
        export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )
        server = ThreadedMotoServer(port=8077)
        server.start()

        try:
            # Upload a file to catalog-bucket
            catalog_bucket = "catalog-bucket"
            s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)
            object_cotent = "testing\n"
            s3_handler.s3_client.put_object(
                Bucket=catalog_bucket,
                Key="S1_L1/images/may24C355000e4102500n.tif",
                Body=object_cotent,
            )

            response = client.get(
                "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/COG",
            )
            assert response.status_code == 302
            # Check that response is a url not file content!
            assert response.content != object_cotent

            # call the redirected url
            product_content = requests.get(response.content.decode().replace('"', "").strip("'"), timeout=10)
            assert product_content.status_code == 200
            # check that content is the same as the original file
            assert product_content.content.decode() == object_cotent

            assert client.get("/catalog/collections/toto:S1_L1/items/INCORRECT_ITEM_ID/download/COG").status_code == 404
            s3_handler.delete_bucket_completely(catalog_bucket)

        finally:
            server.stop()
            # Remove bucket credentials form env variables / should create a s3_handler without credentials error
            clear_aws_credentials()

        response = client.get("/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/COG")
        assert response.status_code == 400
        assert response.content == b'"Could not find s3 credentials"'

    @pytest.mark.unit
    def test_failure_while_moving_files_between_buckets(self, client, mocker, a_correct_feature):
        """Test failure in transferring files between buckets."""
        moto_endpoint = "http://localhost:8088"
        export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}

        server = ThreadedMotoServer(port=8088)
        server.start()
        try:
            s3_handler = S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )

            temp_bucket = "temp-bucket"
            catalog_bucket = "catalog-bucket"
            s3_handler.s3_client.create_bucket(Bucket=temp_bucket)
            s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)
            assert not s3_handler.list_s3_files_obj(temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(catalog_bucket, "")

            # Populate temp-bucket with some small files.
            lst_with_files_to_be_copied = [
                "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T902.nc",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=temp_bucket, Key=obj, Body="testing\n")
            assert s3_handler.list_s3_files_obj(temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(catalog_bucket, "")
            # mock request body to be {}, therefore it will create a BAD request, and info will not be published.
            mocker.patch(
                "rs_server_catalog.user_catalog.UserCatalogMiddleware.update_stac_item_publication",
                return_value={},
            )
            with pytest.raises(fastapi.HTTPException):
                added_feature = client.post("/catalog/collections/darius:S1_L2/items", json=a_correct_feature)
                # Check if status code is BAD REQUEST
                assert added_feature.status_code == 400
                # If catalog publish fails, catalog_bucket should be empty, and temp_bucket should not be empty.

            assert s3_handler.list_s3_files_obj(temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(catalog_bucket, "")
            # clean up
            s3_handler.delete_bucket_completely(temp_bucket)
            s3_handler.delete_bucket_completely(catalog_bucket)

        finally:
            server.stop()
            clear_aws_credentials()


class TestCatalogPublishFeatureWithoutBucketTransferEndpoint:
    def test_create_new_minimal_feature(self, client):
        minimal_collection = {
            "id": "test_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "test_owner",
        }
        response = client.post("/catalog/collections", json=minimal_collection)
