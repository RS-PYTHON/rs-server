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

"""Test module for streaming tasks."""

import os

import pytest
from rs_server_common.authentication.token_auth import TokenAuth
from rs_server_staging.processors.processor_staging import Staging
from rs_server_staging.processors.tasks import streaming_task
from rs_server_staging.utils.asset_info import AssetInfo


class TestStreaming:
    """Test class for Staging processor"""

    def test_streaming_task(
        self,
        mocker,
        config,
    ):
        """Test successful streaming task execution"""

        # Mock environment variables
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "fake_endpoint",
                "S3_REGION": "fake_region",
            },
        )
        s3_key = "s3_path/file.zip"
        test_asset_info = AssetInfo(product_url="https://example.com/product.zip", s3_file=s3_key, s3_bucket="bucket")

        # Mock S3StorageHandler instance
        mock_s3_handler = mocker.Mock()
        mock_s3_handler.s3_streaming_upload.side_effect = s3_key
        mocker.patch("rs_server_staging.processors.tasks.S3StorageHandler", return_value=mock_s3_handler)

        assert (
            streaming_task(
                asset_info=test_asset_info,
                config=config,
                auth=TokenAuth("fake_token"),
            )
            == s3_key
        )

        # Ensure token was accessed

        mock_s3_handler.s3_streaming_upload.assert_called_once()

    def test_streaming_task_incorrect_env(self, mocker, config):
        """Test an error when creating S3 handler due to missing env variables"""

        # Patch environment to remove S3_ACCESSKEY
        mocker.patch.dict(
            os.environ,
            {"S3_SECRETKEY": "fake_secret_key", "S3_ENDPOINT": "fake_endpoint", "S3_REGION": "fake_region"},
        )
        test_asset_info = AssetInfo(
            product_url="https://example.com/product.zip",
            s3_file="file.zip",
            s3_bucket="bucket",
        )

        with pytest.raises(ValueError, match="Cannot create s3 connector object."):
            streaming_task(
                asset_info=test_asset_info,
                config=config,
                auth=TokenAuth("fake_token"),
            )

    def test_streaming_task_runtime_error(self, mocker, config):
        """Test a runtime error during streaming"""

        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "fake_endpoint",
                "S3_REGION": "fake_region",
            },
        )
        test_asset_info = AssetInfo("https://example.com/product.zip", "file.zip", "bucket")
        # Mock the s3 handler
        mock_s3_handler = mocker.Mock()
        mocker.patch("rs_server_staging.processors.tasks.S3StorageHandler", return_value=mock_s3_handler)
        # Mock streaming upload to raise RuntimeError
        mock_s3_handler.s3_streaming_upload.side_effect = RuntimeError("Streaming failed")
        with pytest.raises(
            ValueError,
            match=r"Dask task failed to stream file from https://example.com/product.zip to s3://bucket/file.zip",
        ):
            streaming_task(
                asset_info=test_asset_info,
                config=config,
                auth=TokenAuth("fake_token"),
            )

    def test_streaming_task_connection_retry(self, mocker, config):
        """Test retry mechanism for ConnectionError"""
        s3_max_retries_env_var = 3
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "fake_endpoint",
                "S3_REGION": "fake_region",
                "S3_RETRY_TIMEOUT": "1",
                "S3_MAX_RETRIES": str(s3_max_retries_env_var),
            },
        )
        test_asset_info = AssetInfo("https://example.com/product.zip", "file.zip", "bucket")

        # Mock streaming upload to fail multiple times
        mock_s3_handler = mocker.Mock()
        mock_s3_handler.s3_streaming_upload.side_effect = ConnectionError("Streaming failed")
        mocker.patch("rs_server_staging.processors.tasks.S3StorageHandler", return_value=mock_s3_handler)

        with pytest.raises(
            ValueError,
            match=r"Dask task failed to stream file from https://example.com/product.zip to s3://bucket/file.zip",
        ):
            streaming_task(
                asset_info=test_asset_info,
                config=config,
                auth=TokenAuth("fake_token"),
            )

        # Ensure retries happened
        assert mock_s3_handler.s3_streaming_upload.call_count == s3_max_retries_env_var


class TestPrepareStreaming:
    """Class that groups tests for methods that prepare inputs for streaming process."""

    def test_create_streaming_list_all_downloaded(self, mocker, staging_instance: Staging):
        """Test create_streaming_list when all features are already downloaded."""
        features = [mocker.Mock(id=1), mocker.Mock(id=2)]

        # Create a mock catalog response indicating all features have been downloaded
        catalog_response = {"context": {"returned": 2}, "features": [{"id": 1}, {"id": 2}]}

        # Call the method under test
        staging_instance.create_streaming_list(features, catalog_response)

        # Assert that stream_list is empty
        assert staging_instance.stream_list == []

    def test_create_streaming_list_no_download(self, mocker, staging_instance: Staging):
        """Test create_streaming_list when no features are found in the catalog."""
        features = [mocker.Mock(id=1), mocker.Mock(id=2)]

        # Create a mock catalog response with no features found
        catalog_response = {"context": {"returned": 0}, "features": []}

        staging_instance.create_streaming_list(features, catalog_response)

        # Assert that stream_list contains all features
        assert staging_instance.stream_list == features

    def test_create_streaming_list_partial_download(self, mocker, staging_instance: Staging):
        """Test create_streaming_list when some features are not yet downloaded."""
        feature_1 = mocker.Mock(id=1)
        feature_2 = mocker.Mock(id=2)
        feature_3 = mocker.Mock(id=3)
        features = [feature_1, feature_2, feature_3]

        # Create a mock catalog response indicating only some features have been downloaded
        # Only feature 1 has been already staged
        catalog_response = {"context": {"returned": 1}, "features": [{"id": 1}]}

        staging_instance.create_streaming_list(features, catalog_response)

        # Assert that stream_list contains features 2 and 3 (not downloaded)
        assert staging_instance.stream_list == [feature_2, feature_3]

    def test_create_streaming_list_wrong_catalog_input(self, mocker, staging_instance: Staging):
        """Test create_streaming_list when a wrong response is received from the catalog."""
        feature_1 = mocker.Mock(id=1)
        feature_2 = mocker.Mock(id=2)
        feature_3 = mocker.Mock(id=3)
        features = [feature_1, feature_2, feature_3]

        # Create a mock catalog response which is malformed
        catalog_response = {"context": {"returned": 1}, "wrong_key": [{"id": 1}]}

        with pytest.raises(
            RuntimeError,
            match="The 'features' field is missing in the response from the catalog service.",
        ):
            staging_instance.create_streaming_list(features, catalog_response)

    def test_prepare_streaming_tasks_all_valid(self, mocker, staging_instance: Staging):
        """Test prepare_streaming_tasks when all assets are valid."""
        # clean the already mocked assets
        staging_instance.assets_info = []
        catalog_collection = "test_collection"
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {
            "asset1": mocker.Mock(href="https://example.com/asset1"),
            "asset2": mocker.Mock(href="https://example.com/asset2"),
        }

        result = staging_instance.prepare_streaming_tasks(catalog_collection, feature)

        # Assert that the method returns True
        assert result is True
        # Assert that assets_info has been populated correctly
        assert staging_instance.assets_info == [
            AssetInfo(
                "https://example.com/asset1",
                f"{catalog_collection}/{feature.id}/asset1",
                "rspython-ops-catalog-all-production",
            ),
            AssetInfo(
                "https://example.com/asset2",
                f"{catalog_collection}/{feature.id}/asset2",
                "rspython-ops-catalog-all-production",
            ),
        ]
        # Assert that asset hrefs are updated correctly
        assert feature.assets["asset1"].href == f"s3://rtmpop/{catalog_collection}/{feature.id}/asset1"
        assert feature.assets["asset2"].href == f"s3://rtmpop/{catalog_collection}/{feature.id}/asset2"

    def test_prepare_streaming_tasks_one_invalid(self, mocker, staging_instance: Staging):
        """Test prepare_streaming_tasks when all assets are valid."""
        catalog_collection = "test_collection"
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {
            "asset1": mocker.Mock(href="", title="asset1_title"),
            "asset2": mocker.Mock(href="https://example.com/asset2", title="asset2_title"),
        }
        result = staging_instance.prepare_streaming_tasks(catalog_collection, feature)

        # Assert that the method returns False
        assert result is False

    def test_prepare_streaming_tasks_correctly_retrieves_config(
        self,
        staging_instance: Staging,
        staging_input_for_config_tests_1: dict,
        staging_input_for_config_tests_2: dict,
    ):
        """Test prepare_streaming_tasks with different assets to check
        if bucket_name is properly retrieved in from the config
        """
        staging_instance.assets_info = []
        results = []

        results.append(
            staging_instance.prepare_streaming_tasks(
                staging_input_for_config_tests_1["collection"],
                staging_input_for_config_tests_1["items"]["value"]["features"][0],
            ),
        )
        results.append(
            staging_instance.prepare_streaming_tasks(
                staging_input_for_config_tests_1["collection"],
                staging_input_for_config_tests_1["items"]["value"]["features"][1],
            ),
        )
        results.append(
            staging_instance.prepare_streaming_tasks(
                staging_input_for_config_tests_2["collection"],
                staging_input_for_config_tests_2["items"]["value"]["features"][0],
            ),
        )
        results.append(
            staging_instance.prepare_streaming_tasks(
                staging_input_for_config_tests_2["collection"],
                staging_input_for_config_tests_2["items"]["value"]["features"][1],
            ),
        )

        # Assert that all methods return True
        for result in results:
            assert result is True

        # Assert that each asset_info has the correct bucket name
        assert len(staging_instance.assets_info) == 4
        assert (
            staging_instance.assets_info[0].get_product_url() == "https://fake-data/TC001"
            and staging_instance.assets_info[0].get_s3_bucket() == "rspython-ops-catalog-copernicus-s1-l1"
        )
        assert (
            staging_instance.assets_info[1].get_product_url() == "https://fake-data/TC002"
            and staging_instance.assets_info[1].get_s3_bucket() == "rspython-ops-catalog-all-production"
        )
        assert (
            staging_instance.assets_info[2].get_product_url() == "https://fake-data/TC003"
            and staging_instance.assets_info[2].get_s3_bucket() == "rspython-ops-catalog-copernicus-s1-aux"
        )
        assert (
            staging_instance.assets_info[3].get_product_url() == "https://fake-data/TC004"
            and staging_instance.assets_info[3].get_s3_bucket() == "rspython-ops-catalog-copernicus-s1-aux-infinite"
        )
