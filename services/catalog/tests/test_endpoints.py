"""Integration tests for user_catalog module."""
import copy
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
        assert len(json.loads(response.content)["collections"]) == 0

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
        # !!!!!
        response = client.put("/catalog/collections/second_test_owner:second_test_collection", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_200_OK
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
        first_check_response = client.get("/catalog/collections", params={"owner": "will_be_deleted_owner"})
        first_response_content = json.loads(first_check_response.content)["collections"][0]
        assert first_response_content["description"] == minimal_collection["description"]

        # !!!
        # response = client.get("/catalog/collections/will_be_deleted_owner:will_be_deleted_collection/items")
        # !!!

        # Delete the collection
        delete_response = client.delete("/catalog/collections/will_be_deleted_owner:will_be_deleted_collection")
        assert delete_response.status_code == fastapi.status.HTTP_200_OK
        # Check that collection is correctly deleted
        second_check_response = client.get("/catalog/collections", params={"owner": "will_be_deleted_owner"})
        second_response_content = json.loads(second_check_response.content)
        assert minimal_collection["id"] not in second_response_content["collections"]

    def test_delete_a_non_existent_collection(self, client):
        """
        Test DELETE collection endpoint on non existing collection
        """
        # Should call delete endpoint on a non existent collection id
        with pytest.raises(fastapi.HTTPException):
            delete_response = client.delete("/catalog/collections/non_existent_owner:non_existent_collection")
            assert delete_response.status_code == fastapi.status.HTTP_400_BAD_REQUEST

    def test_delete_a_foreign_collection(self, client):
        """Test DELETE collection endpoint, with a user that has no rights to remove a existing collection."""
        minimal_collection = {
            "id": "correctly_created_collection",
            "type": "Collection",
            "description": "will_be_deleted_description",
            "stac_version": "1.0.0",
            "owner": "owner_with_rights",
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_200_OK
        with pytest.raises(fastapi.HTTPException):
            delete_response = client.delete("/catalog/collections/owner_with_no_rights:correctly_created_collection")
            # To be changed with 405 not allowed after UAC
            assert delete_response.status_code == fastapi.status.HTTP_400_BAD_REQUEST


class TestCatalogPublishFeatureWithBucketTransferEndpoint:
    """This class is used to group tests that just post a feature on catalogDB without moving assets."""

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

            with pytest.raises(fastapi.HTTPException):
                assert (
                    client.get("/catalog/collections/toto:S1_L1/items/INCORRECT_ITEM_ID/download/COG").status_code
                    == 404
                )

        finally:
            s3_handler.delete_bucket_completely(catalog_bucket)
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
    """Class used to group tests that publish a collection and move assets between buckets."""

    def test_create_new_minimal_feature(self, client, a_correct_feature):
        """Test that a feature is correctly published into catalogDB
        ENDPOINT: POST /catalog/collections/{user:collection}/items
        ENDPOINT: GET /catalog/collections/{user:collection}/items
        ENDPOINT: GET /catalog/collections/{user:collection}/items/{featureID}"""
        minimal_collection = {
            "id": "fixture_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "fixture_owner",
        }
        collection_post_response = client.post("/catalog/collections", json=minimal_collection)
        assert collection_post_response.status_code == fastapi.status.HTTP_200_OK
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_200_OK
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
        # Cleanup the test
        client.delete("/catalog/collections/fixture_owner:fixture_collection")

    def test_get_non_existent_feature(self, client, a_minimal_collection):
        """
        Testing GET feature endpoint with a non-existent feature ID.
        """
        # Try to get a non-existent feature from a non-existing collection
        with pytest.raises(fastapi.HTTPException):
            feature_post_response = client.get("/catalog/collections/non_owner:non_collection/items/non_feature_id")
            assert feature_post_response.status_code == fastapi.status.HTTP_404_NOT_FOUND
            # Try to get a non-existent feature from an existing collection
            feature_post_response = client.get(
                "/catalog/collections/fixture_owner:fixture_collection/items/incorrect_feature_id",
            )
            assert feature_post_response.status_code == fastapi.status.HTTP_404_NOT_FOUND
        # Cleanup the test
        client.delete("/catalog/collections/fixture_owner:fixture_collection")

    def test_update_with_a_correct_feature(self, client, a_correct_feature):
        """
        ENDPOINT: PUT: /catalog/collections/{user:collection}/items/{featureID}
        """
        minimal_collection = {
            "id": "fixture_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "fixture_owner",
        }
        collection_post_response = client.post("/catalog/collections", json=minimal_collection)
        assert collection_post_response.status_code == fastapi.status.HTTP_200_OK
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_200_OK
        # Update the feature and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = [77]
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

        # Cleanup the test
        client.delete("/catalog/collections/fixture_owner:fixture_collection")

    def test_update_with_a_incorrect_feature(self, client, a_correct_feature):
        """Testing POST feature endpoint with a wrong-formatted field (BBOX)."""
        minimal_collection = {
            "id": "fixture_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "fixture_owner",
        }
        collection_post_response = client.post("/catalog/collections", json=minimal_collection)
        assert collection_post_response.status_code == fastapi.status.HTTP_200_OK
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_200_OK
        # Update the feature with an incorrect value and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = "Incorrect_bbox_value"

        with pytest.raises(fastapi.HTTPException):
            client.put(
                f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
                json=updated_feature_sent,
            )
        # Cleanup the test
        client.delete("/catalog/collections/fixture_owner:fixture_collection")

    def test_delete_a_correct_feature(self, client, a_correct_feature):
        """
        ENDPOINT: DELETE: /catalog/collections/{user:collection}/items/{featureID}
        """
        minimal_collection = {
            "id": "fixture_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "fixture_owner",
        }
        collection_post_response = client.post("/catalog/collections", json=minimal_collection)
        assert collection_post_response.status_code == fastapi.status.HTTP_200_OK
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_200_OK
        # Delete the feature from catalogDB
        delete_response = client.delete(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )
        assert delete_response.status_code == fastapi.status.HTTP_200_OK
        # Test that feature was correctly removed from catalogDB
        with pytest.raises(fastapi.HTTPException):
            client.get(f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}")
        # Test that collection is now empty
        collection_content_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert collection_content_response.status_code == fastapi.status.HTTP_200_OK
        collection_content_response = json.loads(collection_content_response.content)
        assert collection_content_response["context"]["returned"] == 0
        # Cleanup the test
        client.delete("/catalog/collections/fixture_owner:fixture_collection")

    def test_delete_a_non_existing_feature(self, client):
        """
        Test DELETE feature endpoint on non-existing feature.
        """
        minimal_collection = {
            "id": "fixture_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "fixture_owner",
        }
        collection_post_response = client.post("/catalog/collections", json=minimal_collection)
        assert collection_post_response.status_code == fastapi.status.HTTP_200_OK
        with pytest.raises(fastapi.HTTPException):
            client.delete("/catalog/collections/fixture_owner:fixture_collection/items/non_existent_feature")
        # Cleanup the test
        client.delete("/catalog/collections/fixture_owner:fixture_collection")
