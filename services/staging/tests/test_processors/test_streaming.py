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
import yaml
from rs_server_common.authentication.authentication_to_external import (
    S3ExternalAuthenticationConfig,
)
from rs_server_common.authentication.token_auth import TokenAuth
from rs_server_staging.processors.processor_staging import Staging
from rs_server_staging.processors.tasks import (
    create_asset_info_with_s3_auth,
    find_credentials_for_external_s3_storage,
    prepare_streaming_tasks,
    streaming_task,
)
from rs_server_staging.utils.asset_info import (
    AssetInfo,
    IncompleteAssetError,
    IncompleteFeatureError,
)
from rs_server_staging.utils.rspy_models import Feature
from stac_pydantic.shared import Asset

# pylint: disable=unused-argument


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
        mock_s3_handler.s3_streaming_from_http.side_effect = s3_key
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

        mock_s3_handler.s3_streaming_from_http.assert_called_once()

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
        mock_s3_handler.s3_streaming_from_http.side_effect = RuntimeError("Streaming failed")
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
        mock_s3_handler.s3_streaming_from_http.side_effect = ConnectionError("Streaming failed")
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
        assert mock_s3_handler.s3_streaming_from_http.call_count == s3_max_retries_env_var


class TestPrepareStreaming:
    """Class that groups tests for methods that prepare inputs for streaming process."""

    # === All constants are used for unit tests below, they are here to reduce replication
    # Example of YAML content for credentials for regular station
    TEST_YAML_STATION_CREDENTIALS = """
        genericstation:
            domain: generic.station.test
            service:
                name: adgs
                url: "http://test_url:6000"
            authentication:
                auth_type: oauth2
                token_url: http://test_url:6000/oauth2/token
                grant_type: password
                username: test
                password: test
                client_id: client_id
                client_secret: client_secret
                authorization: Basic test
    """
    # Example of YAML content for credentials for external s3
    TEST_YAML_S3_CREDENTIALS = """
        s3external:
            domain: some.domain.test
            service:
                name: s3
                url: "https://some.domain.test"
            authentication:
                auth_type: s3
                access_key: correct_access
                secret_key: correct_secret
    """
    # Storage scheme matching credentials in TEST_YAML_S3_CREDENTIALS
    TEST_STORAGE_SCHEME_EXISTS = {
        "type": "custom-s3",
        "title": "External S3",
        "platform": "https://some.domain.test",
        "description": "Test storage scheme with existing credentials",
        "requester_pays": False,
    }
    # Storage scheme with no matching credentials
    TEST_STORAGE_SCHEME_DOESNT_EXISTS = {
        "type": "custom-s3",
        "title": "External S3",
        "platform": "https://unknown.domain.test",
        "description": "Test storage scheme with no existing credentials",
        "requester_pays": False,
    }
    # Asset dictionary with storage refs to match with TEST_STORAGE_SCHEME_EXISTS and TEST_STORAGE_SCHEME_DOESNT_EXISTS
    TEST_ASSET_WITH_STORAGE_REFS = {
        "href": "s3://testdata/anyasset.tiff",
        "file:size": 1,
        "file:checksum": "12345",
        "file:local_path": "path/anydata.tiff",
        "auth:refs": ["s3"],
        "storage:refs": ["notexisting-s3", "existing-s3"],
    }

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

    def test_prepare_streaming_tasks_all_valid(self, mocker, set_config_file_env_var):
        """Test prepare_streaming_tasks when all assets are valid."""
        catalog_collection = "test_collection"
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {
            "asset1": mocker.Mock(href="https://example.com/asset1"),
            "asset2": mocker.Mock(href="https://example.com/asset2"),
        }

        result = prepare_streaming_tasks(catalog_collection, feature, "staging_user")

        expected_assets_info = [
            AssetInfo(
                "https://example.com/asset1",
                f"staging_user/{catalog_collection}/{feature.id}/asset1",
                "rspython-ops-catalog-all-production",
            ),
            AssetInfo(
                "https://example.com/asset2",
                f"staging_user/{catalog_collection}/{feature.id}/asset2",
                "rspython-ops-catalog-all-production",
            ),
        ]
        # Assert that the method returns expected assets info
        assert result == expected_assets_info

        # Assert that asset hrefs are updated correctly
        assert feature.assets["asset1"].href == f"s3://rtmpop/staging_user/{catalog_collection}/{feature.id}/asset1"
        assert feature.assets["asset2"].href == f"s3://rtmpop/staging_user/{catalog_collection}/{feature.id}/asset2"

    def test_prepare_streaming_tasks_with_s3_asset_all_valid(self, mocker, set_config_file_env_var):
        """Test prepare_streaming_tasks when all assets are valid and one asset needs to be staged from external s3."""
        # Patch credentials retrieval (for s3 asset)
        mock_yaml_content = mock_yaml_content = "external_data_sources:\n" + self.TEST_YAML_S3_CREDENTIALS
        mocker.patch(
            "rs_server_common.authentication.authentication_to_external.CONFIGURATION",
            yaml.safe_load(mock_yaml_content),
        )

        # Prepare asset with S3 source
        s3_asset = Asset(href="s3://testdata/anyasset.tiff")
        setattr(s3_asset, "storage:refs", ["notexisting-s3", "existing-s3"])

        catalog_collection = "test_collection"
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {"asset1": mocker.Mock(href="https://example.com/asset1"), "asset2": s3_asset}

        # Add expected storage schemes to Feature
        storage_schemes = {
            "notexisting-s3": self.TEST_STORAGE_SCHEME_DOESNT_EXISTS,
            "existing-s3": self.TEST_STORAGE_SCHEME_EXISTS,
        }
        feature.properties = {"storage:schemes": storage_schemes}

        result = prepare_streaming_tasks(catalog_collection, feature, "staging_user")

        expected_assets_info = [
            AssetInfo(
                "https://example.com/asset1",
                f"staging_user/{catalog_collection}/{feature.id}/asset1",
                "rspython-ops-catalog-all-production",
            ),
            AssetInfo(
                "s3://testdata/anyasset.tiff",
                f"staging_user/{catalog_collection}/{feature.id}/asset2",
                "rspython-ops-catalog-all-production",
                "s3",
                "https://some.domain.test",
                "correct_access",
                "correct_secret",
            ),
        ]
        # Assert that the method returns expected assets info
        assert result == expected_assets_info

    def test_prepare_streaming_tasks_one_invalid(self, mocker, set_config_file_env_var):
        """Test prepare_streaming_tasks when all assets are valid."""
        catalog_collection = "test_collection"
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {
            "asset1": mocker.Mock(href="", title="asset1_title"),
            "asset2": mocker.Mock(href="https://example.com/asset2", title="asset2_title"),
        }
        result = prepare_streaming_tasks(catalog_collection, feature, "staging_user")

        # Assert that the method returns None
        assert result is None

    def test_prepare_streaming_tasks_correctly_retrieves_config(
        self,
        set_config_file_env_var,
        staging_input_for_config_tests_1: dict,
        staging_input_for_config_tests_2: dict,
    ):
        """Test prepare_streaming_tasks with different assets to check
        if bucket_name is properly retrieved in from the config
        """
        results = []

        results += prepare_streaming_tasks(
            staging_input_for_config_tests_1["collection"],
            staging_input_for_config_tests_1["items"]["value"]["features"][0],
            "staging_user",
        )
        results += prepare_streaming_tasks(
            staging_input_for_config_tests_1["collection"],
            staging_input_for_config_tests_1["items"]["value"]["features"][1],
            "staging_user",
        )
        results += prepare_streaming_tasks(
            staging_input_for_config_tests_2["collection"],
            staging_input_for_config_tests_2["items"]["value"]["features"][0],
            "staging_user",
        )
        results += prepare_streaming_tasks(
            staging_input_for_config_tests_2["collection"],
            staging_input_for_config_tests_2["items"]["value"]["features"][1],
            "staging_user",
        )

        # Assert that results doesn't contain None (None is returned when preparation fails)
        assert None not in results

        # Assert that each asset_info has the correct bucket name
        assert len(results) == 4
        assert (
            results[0].product_url == "https://fake-data/TC001"
            and results[0].s3_bucket == "rspython-ops-catalog-copernicus-s1-l1"
        )
        assert (
            results[1].product_url == "https://fake-data/TC002"
            and results[1].s3_bucket == "rspython-ops-catalog-all-production"
        )
        assert results[2].product_url == "https://fake-data/TC003" and results[2].s3_bucket
        assert (
            results[3].product_url == "https://fake-data/TC004"
            and results[3].s3_bucket == "rspython-ops-catalog-copernicus-s1-aux-infinite"
        )

    def test_create_asset_info_with_s3_auth_successful(self, mocker):
        """Test test_create_asset_info_with_s3_auth when everything is ok"""
        # Patch credentials retrieval
        mock_yaml_content = mock_yaml_content = "external_data_sources:\n" + self.TEST_YAML_S3_CREDENTIALS
        mocker.patch(
            "rs_server_common.authentication.authentication_to_external.CONFIGURATION",
            yaml.safe_load(mock_yaml_content),
        )

        # Input asset with correct s3 source
        test_asset_name = "test_asset"
        test_asset = self.TEST_ASSET_WITH_STORAGE_REFS

        # Input feature with correct storage schemes (other fields reduced to minimum to keep it simple)
        storage_schemes = {
            "notexisting-s3": self.TEST_STORAGE_SCHEME_DOESNT_EXISTS,
            "existing-s3": self.TEST_STORAGE_SCHEME_EXISTS,
        }
        test_feature = Feature(
            type="Feature",
            properties={"storage:schemes": storage_schemes},
            id="123456",
            stac_version="1.0.0",
            assets={test_asset_name: test_asset},
            stac_extensions=[],
        )

        # Other inputs
        test_s3_file = "test_s3_file"
        test_s3_bucket = "test_s3_bucket"

        # Expected asset_info
        expected_result = AssetInfo(  # nosec B106
            product_url="s3://testdata/anyasset.tiff",
            s3_file=test_s3_file,
            s3_bucket=test_s3_bucket,
            origin_service="s3",
            external_s3_endpoint_url="https://some.domain.test",
            external_s3_access_key="correct_access",
            external_s3_secret_key="correct_secret",
        )

        assert (
            create_asset_info_with_s3_auth(
                feature=test_feature,
                asset_name=test_asset_name,
                asset_content=test_asset,
                s3_file=test_s3_file,
                s3_bucket=test_s3_bucket,
            )
            == expected_result
        )

    def test_create_asset_info_with_s3_auth_failed(self, mocker):
        """Test all error cases of test_create_asset_info_with_s3_auth: incomplete asset,
        incomplete feature, no credentials found
        """
        # Patch credentials retrieval (we use unexisting ones to test error case when no correct credential is found)
        mock_yaml_content = mock_yaml_content = "external_data_sources:\n" + self.TEST_YAML_STATION_CREDENTIALS
        mocker.patch(
            "rs_server_common.authentication.authentication_to_external.CONFIGURATION",
            yaml.safe_load(mock_yaml_content),
        )
        # Other inputs
        test_s3_file = "test_s3_file"
        test_s3_bucket = "test_s3_bucket"
        test_asset_name = "test_asset"
        # Feature with missing field
        test_feature_missing_field = Feature(
            type="Feature",
            properties={},
            id="123456",
            stac_version="1.0.0",
            assets={test_asset_name: self.TEST_ASSET_WITH_STORAGE_REFS},
            stac_extensions=[],
        )
        # Correct feature
        storage_schemes = {
            "notexisting-s3": self.TEST_STORAGE_SCHEME_DOESNT_EXISTS,
            "existing-s3": self.TEST_STORAGE_SCHEME_EXISTS,
        }
        test_feature = Feature(
            type="Feature",
            properties={"storage:schemes": storage_schemes},
            id="123456",
            stac_version="1.0.0",
            assets={test_asset_name: self.TEST_ASSET_WITH_STORAGE_REFS},
            stac_extensions=[],
        )

        # Test cases of asset or feature without needed field
        with pytest.raises(IncompleteAssetError):
            create_asset_info_with_s3_auth(None, "", {}, test_s3_file, test_s3_bucket)
        with pytest.raises(IncompleteFeatureError):
            create_asset_info_with_s3_auth(
                test_feature_missing_field,
                test_asset_name,
                self.TEST_ASSET_WITH_STORAGE_REFS,
                test_s3_file,
                test_s3_bucket,
            )

        # Test case when everything is correct but no credentials are found
        with pytest.raises(RuntimeError):
            create_asset_info_with_s3_auth(
                test_feature,
                test_asset_name,
                self.TEST_ASSET_WITH_STORAGE_REFS,
                test_s3_file,
                test_s3_bucket,
            )

    def test_find_credentials_for_external_s3_storage_successful(self, mocker):
        """Test that credentials are correctly retrieved when they exist."""
        mock_yaml_content = (
            "external_data_sources:\n" + self.TEST_YAML_S3_CREDENTIALS + self.TEST_YAML_STATION_CREDENTIALS
        )
        mocker.patch(
            "rs_server_common.authentication.authentication_to_external.CONFIGURATION",
            yaml.safe_load(mock_yaml_content),
        )

        test_storage_scheme_name = "external-s3"
        expected_configuration = S3ExternalAuthenticationConfig(
            "s3external",
            "some.domain.test",
            "s3",
            "https://some.domain.test",
            "s3",
            "correct_access",
            "correct_secret",
        )
        assert (
            find_credentials_for_external_s3_storage(self.TEST_STORAGE_SCHEME_EXISTS, test_storage_scheme_name)
            == expected_configuration
        )

    def test_find_credentials_for_external_s3_storage_failed(self, mocker):
        """Test that function returns empty strings for each error case."""
        mock_yaml_content = mock_yaml_content = "external_data_sources:\n" + self.TEST_YAML_STATION_CREDENTIALS
        mocker.patch(
            "rs_server_common.authentication.authentication_to_external.CONFIGURATION",
            yaml.safe_load(mock_yaml_content),
        )

        test_storage_scheme_name = "external-s3"
        missing_field_test_storage_scheme = {
            "type": "custom-s3",
            "title": "External S3",
            "description": "Test storage scheme",
            "requester_pays": True,
        }
        unknown_platform_test_storage_scheme = self.TEST_STORAGE_SCHEME_DOESNT_EXISTS
        wrong_platform_test_storage_scheme = {
            "type": "custom-s3",
            "title": "External S3",
            "platform": "https://generic.station.test",
            "description": "Test storage scheme",
            "requester_pays": True,
        }

        assert not find_credentials_for_external_s3_storage(
            missing_field_test_storage_scheme,
            test_storage_scheme_name,
        )
        assert not find_credentials_for_external_s3_storage(
            unknown_platform_test_storage_scheme,
            test_storage_scheme_name,
        )
        assert not find_credentials_for_external_s3_storage(
            wrong_platform_test_storage_scheme,
            test_storage_scheme_name,
        )
