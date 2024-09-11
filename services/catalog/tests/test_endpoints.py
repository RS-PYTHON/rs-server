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


# pylint: disable=too-many-lines

"""Integration tests for user_catalog module."""

import copy
import json
import os
import os.path as osp
import pathlib

# pylint: disable=unused-argument
import time
from datetime import datetime, timedelta

import fastapi
import pytest
import requests
import yaml
from moto.server import ThreadedMotoServer
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler

from .conftest import RESOURCES_FOLDER  # pylint: disable=no-name-in-module

# Resource folders specified from the parent directory of this current script
S3_RSC_FOLDER = osp.realpath(osp.join(osp.dirname(__file__), "resources", "s3"))
ISO_8601_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


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
    with open(RESOURCES_FOLDER / "s3" / "s3.yml", "r", encoding="utf-8") as f:
        s3_config = yaml.safe_load(f)
        os.environ.update(s3_config["s3"])
        os.environ.update(s3_config["boto"])


def clear_aws_credentials():
    """Clear AWS credentials from environment variables."""
    with open(RESOURCES_FOLDER / "s3" / "s3.yml", "r", encoding="utf-8") as f:
        s3_config = yaml.safe_load(f)
        for env_var in list(s3_config["s3"].keys()) + list(s3_config["boto"].keys()):
            del os.environ[env_var]


def test_status_code_200_docs_if_good_endpoints(client):  # pylint: disable=missing-function-docstring
    response = client.get("/catalog/api.html")
    assert response.status_code == fastapi.status.HTTP_200_OK


def test_update_stac_catalog_metadata(client):
    """
    Test the update of the stac catalog metadata when the `/catalog/ endpoint is called
    """
    default_txt = "stac-fastapi"
    id_txt = "rs-python"
    title_txt = "RS-PYTHON STAC Catalog"
    description_txt = "STAC catalog of Copernicus Reference System Python"

    response = client.get("/catalog/")
    assert response.status_code == fastapi.status.HTTP_200_OK
    resp_dict = json.loads(response.content)
    assert resp_dict["id"] == default_txt
    assert resp_dict["title"] == default_txt
    assert resp_dict["description"] == default_txt

    os.environ["CATALOG_METADATA_ID"] = id_txt
    response = client.get("/catalog/")
    assert response.status_code == fastapi.status.HTTP_200_OK
    resp_dict = json.loads(response.content)
    assert resp_dict["id"] == id_txt
    assert resp_dict["title"] == default_txt
    assert resp_dict["description"] == default_txt

    os.environ["CATALOG_METADATA_TITLE"] = title_txt
    os.environ["CATALOG_METADATA_DESCRIPTION"] = description_txt
    response = client.get("/catalog/")
    assert response.status_code == fastapi.status.HTTP_200_OK
    resp_dict = json.loads(response.content)
    assert resp_dict["id"] == id_txt
    assert resp_dict["title"] == title_txt
    assert resp_dict["description"] == description_txt


class TestCatalogCollectionSearchEndpoint:  # pylint: disable=too-few-public-methods
    """This class contains integration tests for the endpoit '/catalog/collections/{owner_id}:{collection_id}/search'"""

    def test_get_search_in_toto_s1_l1_collection(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"filter": "width=2500"}

        response = client.get("/catalog/collections/toto:S1_L1/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 2

        test_params = {"filter": "width=300"}

        response = client.get("/catalog/collections/toto:S1_L1/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 0

    def test_post_search_in_toto_s1_l1_collection(self, client):  # pylint: disable=missing-function-docstring
        cql2_json_query = {
            "filter-lang": "cql2-json",
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "height"}, 2500]},
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                ],
            },
        }

        response = client.post("/catalog/collections/toto:S1_L1/search", json=cql2_json_query)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 2

    def test_search_in_unexisting_collection(self, client):
        """Test that if the collection does not exist, an HTTP 404 error is returned."""

        # Test for GET /catalog/collections/{owner_id}:{collection_id}/search
        test_params = {"filter": "width=2500"}
        response = client.get("/catalog/collections/tata:S1_L1/search", params=test_params)
        assert response.status_code == 404  # Checking with unexisting owner_id
        response = client.get("/catalog/collections/toto:notfound/Search", params=test_params)
        assert response.status_code == 404  # Checking with unexisting collection_id

        # Test for POST /catalog/collections/{owner_id}:{collection_id}/search
        cql2_json_query = {
            "filter-lang": "cql2-json",
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "height"}, 2500]},
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                ],
            },
        }

        response = client.post("/catalog/collections/tata:S1_L1/search", json=cql2_json_query)
        assert response.status_code == 404  # Checking with unexisting owner_id
        response = client.post("/catalog/collections/toto:notfound/search", json=cql2_json_query)
        assert response.status_code == 404  # Checking with unexisting collection_id


class TestCatalogSearchEndpoint:
    """This class contains integration tests for the endpoint '/catalog/search'."""

    def test_search_endpoint_with_ids_and_collections(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"ids": "fe916452-ba6f-4631-9154-c249924a122d", "collections": "toto_S1_L1"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
        content = json.loads(response.content)
        assert len(content["features"]) == 1

    def test_search_endpoint_with_filter_owner_id_and_other(self, client):  # pylint: disable=missing-function-docstring
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

    def test_search_endpoint_with_filter_owner_id_only(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "owner='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 2

    def test_search_endpoint_without_collections(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"filter-lang": "cql2-text", "filter": "owner='toto'"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 2

    def test_search_endpoint_without_filter(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "limit": "5"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK

    def test_searh_endpoint_without_owner_id(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 0  # behavior to be determined

    def test_search_endpoint_with_specific_filter(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500"}

        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        content = json.loads(response.content)
        assert len(content["features"]) == 0  # behavior to be determined

    def test_post_search_endpoint(self, client):  # pylint: disable=missing-function-docstring
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

    def test_post_search_endpoint_with_no_filter_lang(self, client):  # pylint: disable=missing-function-docstring
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
        assert response.status_code == 200

    def test_search_in_unexisting_collection(self, client):
        """Test that if the collection does not exist, an HTTP 404 error is returned."""

        # Test for GET /catalog/search
        test_params = {"collections": ["S1_L1"], "filter": "owner='tata'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 404  # Checking with unexisting owner_id
        test_params = {"collections": ["notfound"], "filter": "owner='toto'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 404  # Checking with unexisting collection_id

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
        assert response.status_code == 404  # Checking with unexisting owner_id

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
        assert response.status_code == 404  # Checking with unexisting collection_id

    def test_search_with_collections_and_filter(self, client):  # pylint: disable=missing-function-docstring
        test_params = {"collections": ["toto_S1_L1"], "filter": "width=2500"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == 200
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
        assert response.status_code == 200

    def test_queryables(self, client):  # pylint: disable=missing-function-docstring
        try:
            response = client.get("/catalog/queryables")
            content = json.loads(response.content)
            with open("queryables.json", "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2)
            assert response.status_code == fastapi.status.HTTP_200_OK
        except Exception as e:
            raise RuntimeError("error") from e
        finally:
            pathlib.Path("queryables.json").unlink(missing_ok=True)


# REWORKED TESTS
class TestCatalogPublishCollectionEndpoint:
    """This class is used to group all tests for publishing a collection into catalog DB."""

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
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        # Check that collection status code is 201
        assert response.status_code == fastapi.status.HTTP_201_CREATED
        # Check that internal collection id is set to owner_collection
        assert json.loads(response.content)["id"] == "test_collection"
        assert json.loads(response.content)["owner"] == "test_owner"

        # # Call search endpoint to verify presence of collection in catalog
        # test_params = {"collections": "test_collection", "filter-lang": "cql2-text", "filter": "owner='test_owner'"}
        # response = client.get("/catalog/search", params=test_params)
        # assert response.status_code == fastapi.status.HTTP_200_OK

        # Test that /catalog/collection GET endpoint returns the correct collection id
        response = client.get("/catalog/collections/test_owner:test_collection")
        assert response.status_code == fastapi.status.HTTP_200_OK
        response_content = json.loads(response.content)
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
        response = client.post("/catalog/collections", json=minimal_incorrect_collection)
        assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
        # Check that owner from this collection is not written in catalogDB
        test_params = {"filter-lang": "cql2-text", "filter": "owner='test_incorrect_owner'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        assert len(json.loads(response.content)["features"]) == 0

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
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }

        # Test that collection is correctly published
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_201_CREATED
        # Test that duplicate collection cannot be published
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_409_CONFLICT
        # Change values from collection, try to publish again
        minimal_collection["description"] = "test_description_updated"
        response = client.post("/catalog/collections", json=minimal_collection)
        # Test that is not allowed
        assert response.status_code == fastapi.status.HTTP_409_CONFLICT
        # Check into catalogDB that values are not updated
        response = client.get("/catalog/collections/duplicate_owner:duplicate_collection")
        response_content = json.loads(response.content)
        assert response_content["description"] == "test_description"

    def test_update_a_created_collection(self, client):
        """
        Test that endpoint PUT /catalog/collections updates a collection.
        Endpoint: PUT /catalog/collections.
        Endpoint: PUT /catalog/collections/owner:collection
        """
        minimal_collection = {
            "id": "second_test_collection",
            "type": "Collection",
            "description": "not_updated_test_description",
            "stac_version": "1.0.0",
            "owner": "second_test_owner",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }
        # Post the collection
        post_collection_response = client.post("/catalog/collections", json=minimal_collection)
        assert post_collection_response.status_code == fastapi.status.HTTP_201_CREATED
        # test if is ok written in catalogDB
        get_collection_response = client.get("/catalog/collections/second_test_owner:second_test_collection")
        response_content = json.loads(get_collection_response.content)
        assert response_content["description"] == "not_updated_test_description"

        # Update the collection description and PUT
        minimal_collection["description"] = "the_updated_test_description"
        updated_collection_response = client.put(
            "/catalog/collections/second_test_owner:second_test_collection",
            json=minimal_collection,
        )
        assert updated_collection_response.status_code == fastapi.status.HTTP_200_OK

        # Check that collection is correctly updated
        get_check_collection_response = client.get("/catalog/collections/second_test_owner:second_test_collection")
        response_content = json.loads(get_check_collection_response.content)
        assert response_content["description"] == "the_updated_test_description"

        # cleanup
        client.delete("/catalog/collections/second_test_owner:second_test_collection")

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
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_201_CREATED

        # Check that collection is correctly published
        first_check_response = client.get("/catalog/collections/will_be_deleted_owner:will_be_deleted_collection")
        first_response_content = json.loads(first_check_response.content)
        assert first_response_content["description"] == minimal_collection["description"]

        # Delete the collection
        delete_response = client.delete("/catalog/collections/will_be_deleted_owner:will_be_deleted_collection")
        assert delete_response.status_code == fastapi.status.HTTP_200_OK
        # Check that collection is correctly deleted
        second_check_response = client.get("/catalog/collections/", params={"owner": "will_be_deleted_owner"})
        assert second_check_response.status_code == fastapi.status.HTTP_404_NOT_FOUND

    def test_delete_a_non_existent_collection(self, client):
        """
        Test DELETE collection endpoint on non existing collection
        """
        # Should call delete endpoint on a non existent collection id
        delete_response = client.delete("/catalog/collections/non_existent_owner:non_existent_collection")
        assert delete_response.status_code == fastapi.status.HTTP_404_NOT_FOUND

    def test_delete_a_foreign_collection(self, client):
        """Test DELETE collection endpoint, with a user that has no rights to remove an existing collection."""
        minimal_collection = {
            "id": "correctly_created_collection",
            "type": "Collection",
            "description": "will_be_deleted_description",
            "stac_version": "1.0.0",
            "owner": "owner_with_rights",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_201_CREATED
        delete_response = client.delete("/catalog/collections/owner_with_no_rights:correctly_created_collection")
        # To be changed with 405 not allowed after UAC
        assert delete_response.status_code == fastapi.status.HTTP_404_NOT_FOUND

    def test_delete_non_empty_collection(self, client, a_minimal_collection, a_correct_feature):
        """
        Test that a collection than contain features can be successfully deleted.
        """
        first_get_collection_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert first_get_collection_response.status_code == fastapi.status.HTTP_200_OK
        assert json.loads(first_get_collection_response.content)["context"]["returned"] == 0
        # Post the feature to the collection
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["collection"] = "fixture_collection"
        post_collection_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=updated_feature_sent,
        )
        assert post_collection_response.status_code == fastapi.status.HTTP_201_CREATED
        # Test that the collection is not empty
        second_get_collection_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert second_get_collection_response.status_code == fastapi.status.HTTP_200_OK
        assert json.loads(second_get_collection_response.content)["context"]["returned"] > 0
        # Delete the collection
        delete_response = client.delete("/catalog/collections/fixture_owner:fixture_collection")
        assert delete_response.status_code == fastapi.status.HTTP_200_OK
        # Test that the collection is removed, the request raises a 404 exception
        response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND


class TestCatalogPublishFeatureWithBucketTransferEndpoint:
    """This class is used to group tests that just post a feature on catalogDB without moving assets."""

    temp_bucket = "temp-bucket"
    catalog_bucket = "catalog-bucket"

    @pytest.mark.parametrize(
        "owner, collection_id",
        [
            (
                "darius",
                "S1_L2",
            ),
        ],
    )
    def test_timestamps_extension_item(
        self,
        client,
        a_correct_feature,
        owner,
        collection_id,
    ):  # pylint: disable=too-many-locals, too-many-arguments
        """Test used to verify that the timestamps extension is correctly set up"""
        # Create moto server and temp / catalog bucket
        moto_endpoint = "http://localhost:8077"
        export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        # Enable bucket transfer
        os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"
        server = ThreadedMotoServer(port=8077)
        server.start()
        try:
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            s3_handler = S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )

            s3_handler.s3_client.create_bucket(Bucket=self.temp_bucket)
            s3_handler.s3_client.create_bucket(Bucket=self.catalog_bucket)

            # Populate temp-bucket with some small files.
            lst_with_files_to_be_copied = [
                "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T902.nc",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=self.temp_bucket, Key=obj, Body="testing\n")
            added_feature = client.post(f"/catalog/collections/{owner}:{collection_id}/items", json=a_correct_feature)
            feature_data = json.loads(added_feature.content)

            current_time = datetime.now()

            # Test that published field is correctly added
            assert "published" in feature_data["properties"]
            published_datetime_format = datetime.strptime(
                feature_data["properties"]["published"],
                ISO_8601_FORMAT,
            )
            assert (
                abs(published_datetime_format - current_time).total_seconds() < 1
            )  # Check that values are close enough.

            # Test that updated field is correctly added
            assert "updated" in feature_data["properties"]
            updated_datetime_format = datetime.strptime(feature_data["properties"]["updated"], ISO_8601_FORMAT)
            assert abs(updated_datetime_format - current_time).total_seconds() < 1

            # Test that expires field is correctly added
            assert "expires" in feature_data["properties"]
            plus_30_days = current_time + timedelta(days=int(os.environ.get("RANGE_EXPIRATION_DATE_IN_DAYS", "30")))
            expires_datetime_format = datetime.strptime(feature_data["properties"]["expires"], ISO_8601_FORMAT)
            assert abs(expires_datetime_format - plus_30_days).total_seconds() < 1
            assert (
                client.delete(
                    f"/catalog/collections/{owner}:{collection_id}/items/S1SIWOCN_20220412T054447_0024_S139",
                ).status_code
                == fastapi.status.HTTP_200_OK
            )
        except Exception as e:
            raise RuntimeError("error") from e
        finally:
            server.stop()
            clear_aws_credentials()
            os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"

    def test_updating_timestamp_item(  # pylint: disable=too-many-locals, too-many-statements
        self,
        client,
        a_correct_feature,
        a_minimal_collection,
    ):
        """Test used to verify update of an item to the catalog."""
        # Create moto server and temp / catalog bucket
        moto_endpoint = "http://localhost:8077"
        export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        # Enable bucket transfer
        os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"
        server = ThreadedMotoServer(port=8077)
        server.start()
        try:
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            s3_handler = S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )

            s3_handler.s3_client.create_bucket(Bucket=self.temp_bucket)
            s3_handler.s3_client.create_bucket(Bucket=self.catalog_bucket)
            assert not s3_handler.list_s3_files_obj(self.temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(self.catalog_bucket, "")

            # Populate temp-bucket with some small files.
            lst_with_files_to_be_copied = [
                "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T902.nc",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=self.temp_bucket, Key=obj, Body="testing\n")

            # check that temp_bucket is not empty
            assert s3_handler.list_s3_files_obj(self.temp_bucket, "")
            # check if temp_bucket content is different from catalog_bucket
            assert sorted(s3_handler.list_s3_files_obj(self.temp_bucket, "")) != sorted(
                s3_handler.list_s3_files_obj(self.catalog_bucket, ""),
            )
            # TC01: Add on Sentinel-1 item to the Catalog with a well-formatted STAC JSON file
            # and a good OBS path. => 201 CREATED
            # Check if that user darius have a collection (Added in conftest -> setup_database)
            # Add a featureCollection to darius collection
            a_correct_feature_copy = copy.deepcopy(a_correct_feature)
            a_correct_feature_copy["collection"] = "fixture_collection"
            added_feature = client.post(
                "/catalog/collections/fixture_owner:fixture_collection/items",
                json=a_correct_feature_copy,
            )

            assert added_feature.status_code == fastapi.status.HTTP_201_CREATED

            content = json.loads(added_feature.content)
            updated_timestamp = content["properties"]["updated"]
            published_timestamp = content["properties"]["published"]
            expires_timestamps = content["properties"]["expires"]

            # Files were moved, check that self.catalog_bucket is not empty
            assert s3_handler.list_s3_files_obj(self.catalog_bucket, "")
            # Check if temp_bucket is now empty
            assert not s3_handler.list_s3_files_obj(self.temp_bucket, "")
            # Check if buckets content is different
            assert s3_handler.list_s3_files_obj(self.temp_bucket, "") != s3_handler.list_s3_files_obj(
                self.catalog_bucket,
                "",
            )
            # Check if catalog bucket content match the initial temp-bucket content
            # If so, files were correctly moved from temp-catalog to bucket catalog.
            assert sorted(s3_handler.list_s3_files_obj(self.catalog_bucket, "")) == sorted(lst_with_files_to_be_copied)

            updated_feature_sent = copy.deepcopy(a_correct_feature_copy)
            updated_feature_sent["bbox"] = [-180.0, -90.0, 180.0, 90.0]
            del updated_feature_sent["collection"]

            path = f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}"
            modified_feature = client.put(path, json=updated_feature_sent)

            assert modified_feature.status_code == fastapi.status.HTTP_200_OK

            updated_content = json.loads(modified_feature.content)

            new_updated_timestamp = updated_content["properties"]["updated"]

            # Test that "updated" field is correctly updated.
            assert updated_timestamp != new_updated_timestamp

            # Test that "published" and "expires" field are inchanged after the update.
            assert updated_content["properties"]["published"] == published_timestamp
            assert updated_content["properties"]["expires"] == expires_timestamps

            assert (
                client.delete(
                    "/catalog/collections/fixture_owner:fixture_collection/items/S1SIWOCN_20220412T054447_0024_S139",
                ).status_code
                == fastapi.status.HTTP_200_OK
            )
        except Exception as e:
            raise RuntimeError("error") from e
        finally:
            server.stop()
            clear_aws_credentials()
            os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"

    def test_updating_assets_in_item(  # pylint: disable=too-many-locals, too-many-statements
        self,
        client,
        a_correct_feature,
        a_minimal_collection,
    ):
        """Test used to verify update of an item to the catalog."""
        # Create moto server and temp / catalog bucket
        moto_endpoint = "http://localhost:8077"
        export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        # Enable bucket transfer
        os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"
        server = ThreadedMotoServer(port=8077)
        server.start()
        try:
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            s3_handler = S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )

            s3_handler.s3_client.create_bucket(Bucket=self.temp_bucket)
            s3_handler.s3_client.create_bucket(Bucket=self.catalog_bucket)
            assert not s3_handler.list_s3_files_obj(self.temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(self.catalog_bucket, "")

            # Populate temp-bucket with some small files.
            lst_with_files_to_be_copied = [
                "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T902.nc",
                "some/other/path/S1SIWOCN_20220412T054447_0024_S139_T902.nc",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=self.temp_bucket, Key=obj, Body="testing\n")
            # check that temp_bucket is not empty
            assert s3_handler.list_s3_files_obj(self.temp_bucket, "")
            # check if temp_bucket content is different from catalog_bucket
            assert sorted(s3_handler.list_s3_files_obj(self.temp_bucket, "")) != sorted(
                s3_handler.list_s3_files_obj(self.catalog_bucket, ""),
            )

            item_test = copy.deepcopy(a_correct_feature)
            # modify the item: change the name of the collection with the fixture_collection
            # delete the last two assets for a later use
            item_test["collection"] = "fixture_collection"
            del item_test["assets"]["S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip"]
            del item_test["assets"]["S1SIWOCN_20220412T054447_0024_S139_T902.nc"]
            resp = client.post(
                "/catalog/collections/fixture_owner:fixture_collection/items",
                json=item_test,
            )
            assert resp.status_code == fastapi.status.HTTP_201_CREATED
            content = json.loads(resp.content)

            assert content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip")
            assert not content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip")
            assert not content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T902.nc")

            content["assets"]["S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip"] = {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "roles": ["data"],
            }
            resp = client.put(
                f"/catalog/collections/fixture_owner:fixture_collection/items/{content['id']}",
                json=content,
            )

            content = json.loads(resp.content)

            assert resp.status_code == fastapi.status.HTTP_200_OK
            assert content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip")
            assert content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip")
            assert not content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T902.nc")

            del content["assets"]["S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip"]
            content["assets"]["S1SIWOCN_20220412T054447_0024_S139_T902.nc"] = {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T902.nc",
                "roles": ["data"],
            }
            resp = client.put(
                f"/catalog/collections/fixture_owner:fixture_collection/items/{content['id']}",
                json=content,
            )
            assert resp.status_code == fastapi.status.HTTP_200_OK
            content = json.loads(resp.content)
            assert not content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip")
            assert content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip")
            assert content.get("assets").get("S1SIWOCN_20220412T054447_0024_S139_T902.nc")

            catalog_files = s3_handler.list_s3_files_obj(self.catalog_bucket, "")
            assert len(catalog_files) == 2
            assert set(catalog_files) == set(
                ["S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip", "S1SIWOCN_20220412T054447_0024_S139_T902.nc"],
            )
            # try to change the path / physical file for an asset, it should not work
            content["assets"]["S1SIWOCN_20220412T054447_0024_S139_T902.nc"] = {
                "href": "s3://temp-bucket/some/other/path/S1SIWOCN_20220412T054447_0024_S139_T902.nc",
                "roles": ["data"],
            }
            resp = client.put(
                f"/catalog/collections/fixture_owner:fixture_collection/items/{content['id']}",
                json=content,
            )
            assert resp.status_code == fastapi.status.HTTP_400_BAD_REQUEST
            content = json.loads(resp.content)
            assert "However, changing an existing path of an asset is not allowed" in content
            temp_list = s3_handler.list_s3_files_obj(self.temp_bucket, "")
            cat_list = s3_handler.list_s3_files_obj(self.catalog_bucket, "")
            print(f"Files in temp bucket: {temp_list}")
            print(f"Files in catalog bucket: {cat_list}")
            assert (
                client.delete(
                    "/catalog/collections/fixture_owner:fixture_collection/items/S1SIWOCN_20220412T054447_0024_S139",
                ).status_code
                == fastapi.status.HTTP_200_OK
            )
        except Exception as e:
            raise RuntimeError("error") from e
        finally:
            server.stop()
            clear_aws_credentials()
            os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"

    @pytest.mark.parametrize(
        "owner, collection_id",
        [
            (
                "darius",
                "S1_L2",
            ),
        ],
    )
    def test_publish_item_update(  # pylint: disable=too-many-locals
        self,
        client,
        a_correct_feature,
        owner,
        collection_id,
    ):
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
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            s3_handler = S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )

            s3_handler.s3_client.create_bucket(Bucket=self.temp_bucket)
            s3_handler.s3_client.create_bucket(Bucket=self.catalog_bucket)
            assert not s3_handler.list_s3_files_obj(self.temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(self.catalog_bucket, "")

            # Populate temp-bucket with some small files.
            lst_with_files_to_be_copied = [
                "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T902.nc",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=self.temp_bucket, Key=obj, Body="testing\n")

            # check that self.temp_bucket is not empty
            assert s3_handler.list_s3_files_obj(self.temp_bucket, "")
            # check if self.temp_bucket content is different from self.catalog_bucket
            assert sorted(s3_handler.list_s3_files_obj(self.temp_bucket, "")) != sorted(
                s3_handler.list_s3_files_obj(self.catalog_bucket, ""),
            )

            # TC01: Add on Sentinel-1 item to the Catalog with a well-formatted STAC JSON file
            # and a good OBS path. => 201 CREATED
            # Check if that user darius have a collection (Added in conftest -> setup_database)
            # Add a featureCollection to darius collection
            added_feature = client.post(f"/catalog/collections/{owner}:{collection_id}/items", json=a_correct_feature)
            assert added_feature.status_code == fastapi.status.HTTP_201_CREATED
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

            # Files were moved, check that self.catalog_bucket is not empty
            assert s3_handler.list_s3_files_obj(self.catalog_bucket, "")
            # Check if self.temp_bucket is now empty
            assert not s3_handler.list_s3_files_obj(self.temp_bucket, "")
            # Check if buckets content is different
            assert s3_handler.list_s3_files_obj(self.temp_bucket, "") != s3_handler.list_s3_files_obj(
                self.catalog_bucket,
                "",
            )
            # Check if catalog bucket content match the initial temp-bucket content
            # If so, files were correctly moved from temp-catalog to bucket catalog.
            assert sorted(s3_handler.list_s3_files_obj(self.catalog_bucket, "")) == sorted(lst_with_files_to_be_copied)
        except Exception as e:
            raise RuntimeError("error") from e
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
        added_feature = client.post(f"/catalog/collections/{owner}:{collection_id}/items", json=a_incorrect_feature)
        # Bad request = 400
        assert added_feature.status_code == fastapi.status.HTTP_400_BAD_REQUEST

    @pytest.mark.unit
    def test_incorrect_bucket_publish(self, client, a_correct_feature):
        """Test used to verify failure when obs path is wrong."""
        # TC03: Add on Sentinel-1 item to the Catalog with a wrong OBS path  => ERROR => 400 Bad Request
        export_aws_credentials()
        item_test = copy.deepcopy(a_correct_feature)
        item_test["id"] = "S1SIWOCN_20220412T054447_0024_S139_TEST"
        item_test["assets"]["S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip"][
            "href"
        ] = "incorrect_s3_url/S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip"
        item_test["assets"]["S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip"][
            "href"
        ] = "incorrect_s3_url/S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip"
        item_test["assets"]["S1SIWOCN_20220412T054447_0024_S139_T902.nc"][
            "href"
        ] = "incorrect_s3_url/S1SIWOCN_20220412T054447_0024_S139_T902.nc"
        response = client.post("/catalog/collections/darius:S1_L2/items", json=item_test)
        assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
        assert "Could not load the S3 key from the asset content" in json.loads(response.content)
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
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            custom_bucket = "some-custom-bucket"
            item_test = copy.deepcopy(a_correct_feature)
            item_test["id"] = "new_feature_id"
            item_test["assets"]["some_file.zarr.zip"] = {}
            item_test["assets"]["some_file.zarr.zip"][
                "href"
            ] = f"s3://{custom_bucket}/correct_location/some_file.zarr.zip"
            item_test["assets"]["some_file.zarr.zip"]["roles"] = ["data"]
            item_test["assets"]["some_file.cog.zip"] = {}
            item_test["assets"]["some_file.cog.zip"][
                "href"
            ] = f"s3://{custom_bucket}/correct_location/some_file.cog.zip"
            item_test["assets"]["some_file.cog.zip"]["roles"] = ["data"]
            item_test["assets"]["some_file.nc"] = {}
            item_test["assets"]["some_file.nc"]["href"] = f"s3://{custom_bucket}/correct_location/some_file.nc"
            item_test["assets"]["some_file.nc"]["roles"] = ["data"]
            del item_test["assets"]["S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip"]
            del item_test["assets"]["S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip"]
            del item_test["assets"]["S1SIWOCN_20220412T054447_0024_S139_T902.nc"]

            s3_handler.s3_client.create_bucket(Bucket=custom_bucket)
            s3_handler.s3_client.create_bucket(Bucket=self.catalog_bucket)
            lst_with_files_to_be_copied = [
                "correct_location/some_file.zarr.zip",
                "correct_location/some_file.cog.zip",
                "correct_location/some_file.nc",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=custom_bucket, Key=obj, Body="testing\n")

            assert s3_handler.list_s3_files_obj(custom_bucket, "")
            assert not s3_handler.list_s3_files_obj(self.catalog_bucket, "")

            added_feature = client.post("/catalog/collections/darius:S1_L2/items", json=item_test)
            assert added_feature.status_code == fastapi.status.HTTP_201_CREATED

            assert not s3_handler.list_s3_files_obj(custom_bucket, "")
            assert s3_handler.list_s3_files_obj(self.catalog_bucket, "")

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
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            # Upload a file to catalog-bucket
            s3_handler.s3_client.create_bucket(Bucket=self.catalog_bucket)
            object_content = "testing\n"
            s3_handler.s3_client.put_object(
                Bucket=self.catalog_bucket,
                Key="S1_L1/images/may24C355000e4102500n.tif",
                Body=object_content,
            )

            response = client.get(
                "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/"
                "may24C355000e4102500n.tif",
            )
            assert response.status_code == fastapi.status.HTTP_302_FOUND
            # Check that response body is empty
            assert response.content == b""

            # call the redirected url
            product_content = requests.get(response.headers["location"], timeout=10)
            assert product_content.status_code == fastapi.status.HTTP_200_OK
            # check that content is the same as the original file
            assert product_content.content.decode() == object_content
            # test with a non-existing asset id
            response = client.get(
                "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/UNKNWON",
            )
            assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND
            assert (
                response.content
                == b"\"Could not find asset named 'UNKNWON' \
from item 'fe916452-ba6f-4631-9154-c249924a122d'\""
            )
            # test with a non-existing item id
            assert (
                client.get("/catalog/collections/toto:S1_L1/items/INCORRECT_ITEM_ID/download/UNKNWON").status_code
                == fastapi.status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            raise RuntimeError("error") from e
        finally:
            server.stop()
            # Remove bucket credentials form env variables / should create a s3_handler without credentials error
            clear_aws_credentials()

        response = client.get(
            "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/"
            "may24C355000e4102500n.tif",
        )
        assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
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
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            s3_handler = S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )

            s3_handler.s3_client.create_bucket(Bucket=self.temp_bucket)
            s3_handler.s3_client.create_bucket(Bucket=self.catalog_bucket)
            assert not s3_handler.list_s3_files_obj(self.temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(self.catalog_bucket, "")

            # Populate temp-bucket with some small files.
            lst_with_files_to_be_copied = [
                "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T902.nc",
            ]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=self.temp_bucket, Key=obj, Body="testing\n")
            assert s3_handler.list_s3_files_obj(self.temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(self.catalog_bucket, "")
            # mock request body to be {}, therefore it will create a BAD request, and info will not be published.
            mocker.patch(
                "rs_server_catalog.user_catalog.UserCatalog.update_stac_item_publication",
                return_value={},
            )
            added_feature = client.post("/catalog/collections/darius:S1_L2/items", json=a_correct_feature)
            # Check if status code is BAD REQUEST
            assert added_feature.status_code == fastapi.status.HTTP_400_BAD_REQUEST
            # If catalog publish fails, self.catalog_bucket should be empty, and
            # self.temp_bucket should not be empty.

            assert s3_handler.list_s3_files_obj(self.temp_bucket, "")
            assert not s3_handler.list_s3_files_obj(self.catalog_bucket, "")
        except Exception as e:
            raise RuntimeError("error") from e
        finally:
            server.stop()
            clear_aws_credentials()


class TestCatalogPublishFeatureWithoutBucketTransferEndpoint:
    """Class used to group tests that publish a collection and move assets between buckets."""

    def test_create_new_minimal_feature(self, client, a_minimal_collection, a_correct_feature):
        """Test that a feature is correctly published into catalogDB
        ENDPOINT: POST /catalog/collections/{user:collection}/items
        ENDPOINT: GET /catalog/collections/{user:collection}/items
        ENDPOINT: GET /catalog/collections/{user:collection}/items/{featureID}"""
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED
        # Check if the future is correctly posted to catalog
        check_features_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert check_features_response.status_code == fastapi.status.HTTP_200_OK
        # Test if query returns only one feature for this collection
        returned_features = json.loads(check_features_response.content)
        assert returned_features["context"]["returned"] == 1
        # Test feature content
        assert returned_features["features"][0]["id"] == a_correct_feature["id"]
        assert returned_features["features"][0]["geometry"] == a_correct_feature["geometry"]
        assert returned_features["features"][0]["properties"]["owner"] == "fixture_owner"
        # Get feature using specific endpoint with featureID
        feature_id = a_correct_feature["id"]
        specific_feature_response = client.get(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
        )
        assert specific_feature_response.status_code == fastapi.status.HTTP_200_OK
        specific_feature = json.loads(check_features_response.content)
        # Check that specific feature is exactly match for previous one
        assert specific_feature["features"][0] == returned_features["features"][0]
        assert (
            client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code
            == fastapi.status.HTTP_200_OK
        )

    def test_get_non_existent_feature(self, client, a_minimal_collection):
        """
        Testing GET feature endpoint with a non-existent feature ID.
        """
        # Try to get a non-existent feature from a non-existing collection
        feature_post_response = client.get("/catalog/collections/non_owner:non_collection/items/non_feature_id")
        assert feature_post_response.status_code == fastapi.status.HTTP_404_NOT_FOUND
        # Try to get a non-existent feature from an existing collection
        feature_post_response = client.get(
            "/catalog/collections/fixture_owner:fixture_collection/items/incorrect_feature_id",
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_404_NOT_FOUND
        assert (
            client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code
            == fastapi.status.HTTP_200_OK
        )

    def test_update_with_a_correct_feature(self, client, a_minimal_collection, a_correct_feature):
        """
        ENDPOINT: PUT: /catalog/collections/{user:collection}/items/{featureID}
        """
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED
        # Update the feature and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = [-180.0, -90.0, 180.0, 90.0]
        del updated_feature_sent["collection"]

        feature_put_response = client.put(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
            json=updated_feature_sent,
        )
        assert feature_put_response.status_code == fastapi.status.HTTP_200_OK
        # Test the updated feature from catalog
        updated_feature = client.get(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )
        assert updated_feature.status_code == fastapi.status.HTTP_200_OK
        updated_feature = json.loads(updated_feature.content)
        # Test that ID has changed, but other arbitrary field not
        assert updated_feature["bbox"] == updated_feature_sent["bbox"]
        assert updated_feature["geometry"] == a_correct_feature["geometry"]
        assert (
            client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code
            == fastapi.status.HTTP_200_OK
        )

    def test_update_timestamp_feature(  # pylint: disable=too-many-locals
        self,
        client,
        a_minimal_collection,
        a_correct_feature,
    ):
        """
        ENDPOINT: PUT: /catalog/collections/{user:collection}/items/{featureID}
        """
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )

        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED

        content = json.loads(feature_post_response.content)
        first_published_date = content["properties"]["published"]
        first_expires_date = content["properties"]["expires"]
        # Update the feature and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = [-180.0, -90.0, 180.0, 90.0]
        del updated_feature_sent["collection"]

        # Test that updated field is correctly updated.
        updated_timestamp = json.loads(feature_post_response.content)["properties"]["updated"]
        time.sleep(1)

        feature_put_response = client.put(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
            json=updated_feature_sent,
        )
        content = json.loads(feature_put_response.content)

        new_updated_timestamp = content["properties"]["updated"]

        # Test that "updated" field is correctly updated.
        assert updated_timestamp != new_updated_timestamp

        # Test that "published" and "expires" field are inchanged after the update.
        assert content["properties"]["published"] == first_published_date
        assert content["properties"]["expires"] == first_expires_date

        assert feature_put_response.status_code == fastapi.status.HTTP_200_OK
        # client.delete("/catalog/collections/fixture_owner:fixture_collection")
        deletion = client.delete("/catalog/collections/fixture_owner:fixture_collection")
        assert deletion.status_code == fastapi.status.HTTP_200_OK

    def test_update_timestamp_feature_fails_with_unfound_item(
        self,
        client,
        a_minimal_collection,
        a_correct_feature,
    ):
        """
        ENDPOINT: PUT: /catalog/collections/{user:collection}/items/{featureID}
        """

        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )

        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED

        # Update the feature and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = [77]
        del updated_feature_sent["collection"]

        path = "/catalog/collections/fixture_owner:fixture_collections/items/NOT_FOUND_ITEM"
        feature_put_response = client.put(
            path,
            json=updated_feature_sent,
        )
        assert feature_put_response.status_code == fastapi.status.HTTP_400_BAD_REQUEST

    def test_update_with_an_incorrect_feature(self, client, a_minimal_collection, a_correct_feature):
        """Testing POST feature endpoint with a wrong-formatted field (BBOX)."""
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        get_response = client.get(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )

        if get_response.status_code == fastapi.status.HTTP_200_OK:
            client.delete(f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}")

        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED
        # Update the feature with an incorrect value and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = "Incorrect_bbox_value"
        del updated_feature_sent["collection"]

        response = client.put(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
            json=updated_feature_sent,
        )
        assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST

    def test_delete_a_correct_feature(self, client, a_minimal_collection, a_correct_feature):
        """
        ENDPOINT: DELETE: /catalog/collections/{user:collection}/items/{featureID}
        """
        a_correct_feature["collection"] = "fixture_collection"

        get_response = client.get(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )

        if get_response.status_code == fastapi.status.HTTP_200_OK:
            client.delete(f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}")

        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED
        # Delete the feature from catalogDB
        delete_response = client.delete(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )
        assert delete_response.status_code == fastapi.status.HTTP_200_OK
        # Test that feature was correctly removed from catalogDB

        response = client.get(f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}")
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND

        # Test that collection is now empty
        collection_content_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert collection_content_response.status_code == fastapi.status.HTTP_200_OK
        collection_content_response = json.loads(collection_content_response.content)
        assert collection_content_response["context"]["returned"] == 0
        assert (
            client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code
            == fastapi.status.HTTP_200_OK
        )

    def test_delete_a_non_existing_feature(self, client, a_minimal_collection):
        """
        Test DELETE feature endpoint on non-existing feature.
        """
        response = client.delete("/catalog/collections/fixture_owner:fixture_collection/items/non_existent_feature")
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND


def test_queryables(client):
    """
    Test Queryables feature endpoint.s
    """
    response = client.get("/catalog/queryables")
    assert response.status_code == fastapi.status.HTTP_200_OK


def test_catalog_catalogs_owner_id_is_disabled(client):
    """
    Test that the endpoint /catalog/catalogs/{owner_id} is no longer working as expected.
    """

    response = client.get("/catalog/catalogs/toto")
    assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
