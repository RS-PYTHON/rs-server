# Copyright 2025 CS Group
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

"""Endpoints tests for features publishing with bucket transfer in catalog"""

# pylint: disable=unused-argument

import copy
import json
import os
from datetime import datetime, timedelta

import fastapi
import pytest
import requests
from moto.server import ThreadedMotoServer
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler

from ..helpers import clear_aws_credentials, export_aws_credentials

ISO_8601_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


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
            assert set(catalog_files) == {
                "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "S1SIWOCN_20220412T054447_0024_S139_T902.nc",
            }
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
        assert "Failed to load the S3 key from the asset content" in json.loads(response.content)
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
                == b"\"Failed to find asset named 'UNKNWON' \
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
        assert response.content == b'"Failed to find s3 credentials"'

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
