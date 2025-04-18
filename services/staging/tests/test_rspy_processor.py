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
"""Test module for Staging processor."""
import asyncio
import os
from datetime import datetime
from unittest.mock import call

import pytest
import requests
from dask_gateway import Gateway
from pygeoapi.util import JobStatus
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.authentication.token_auth import TokenAuth
from rs_server_staging.processors import (
    Staging,
    streaming_task,
)
from rs_server_staging.rspy_models import FeatureCollectionModel

# pylint: disable=undefined-variable
# pylint: disable=no-member
# pylint: disable=too-many-lines


class TestTokenAuth:
    """Class with tests for token auth."""

    def test_token_auth_init(self):
        """Test that the TokenAuth initializes with the correct token."""
        test_value_tkn = "my_test_token"
        auth = TokenAuth(test_value_tkn)
        assert auth.token == test_value_tkn

    def test_token_auth_call(self, mocker):
        """Test that TokenAuth modifies the request headers crrectly."""
        test_value_tkn = "my_test_token"
        auth = TokenAuth(test_value_tkn)

        # Mocking the request object using mocker
        request = mocker.Mock(spec=requests.Request)  # type: ignore
        request.headers = {}

        # Call the auth object with the request
        modified_request = auth(request)

        # Ensure headers were modified correctly
        assert modified_request.headers["Authorization"] == f"Bearer {test_value_tkn}"

    def test_token_auth_repr(self):
        """Test the repr_ method of TokenAuth."""
        auth = TokenAuth("my_test_token")
        assert repr(auth) == "RSPY Token handler"


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

        # Mock S3StorageHandler instance
        mock_s3_handler = mocker.Mock()
        mock_s3_handler.s3_streaming_upload.side_effect = s3_key
        mocker.patch("rs_server_staging.processors.S3StorageHandler", return_value=mock_s3_handler)

        assert (
            streaming_task(
                product_url="https://example.com/product.zip",
                s3_file=s3_key,
                config=config,
                bucket="bucket",
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

        with pytest.raises(ValueError, match="Cannot create s3 connector object."):
            streaming_task(
                product_url="https://example.com/product.zip",
                s3_file="file.zip",
                config=config,
                bucket="bucket",
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
        # Mock the s3 handler
        mock_s3_handler = mocker.Mock()
        mocker.patch("rs_server_staging.processors.S3StorageHandler", return_value=mock_s3_handler)
        # Mock streaming upload to raise RuntimeError
        mock_s3_handler.s3_streaming_upload.side_effect = RuntimeError("Streaming failed")
        with pytest.raises(
            ValueError,
            match=r"Dask task failed to stream file from https://example.com/product.zip to s3://bucket/file.zip",
        ):
            streaming_task(
                product_url="https://example.com/product.zip",
                s3_file="file.zip",
                config=config,
                bucket="bucket",
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

        # Mock streaming upload to fail multiple times
        mock_s3_handler = mocker.Mock()
        mock_s3_handler.s3_streaming_upload.side_effect = ConnectionError("Streaming failed")
        mocker.patch("rs_server_staging.processors.S3StorageHandler", return_value=mock_s3_handler)

        with pytest.raises(
            ValueError,
            match=r"Dask task failed to stream file from https://example.com/product.zip to s3://bucket/file.zip",
        ):
            streaming_task(
                product_url="https://example.com/product.zip",
                s3_file="file.zip",
                config=config,
                bucket="bucket",
                auth=TokenAuth("fake_token"),
            )

        # Ensure retries happened
        assert mock_s3_handler.s3_streaming_upload.call_count == s3_max_retries_env_var


class TestStaging:
    """Test class for Staging processor"""

    @pytest.mark.asyncio
    async def test_execute_with_running_loop(
        self,
        mocker,
        staging_instance: Staging,
        staging_inputs: dict,
        asyncio_loop,
    ):
        """Test execute method while a asyncio loop is running"""
        spy_log_job = mocker.spy(staging_instance, "log_job_execution")
        mock_check_catalog = mocker.patch.object(staging_instance, "check_catalog", return_value=True)
        mock_process_rspy = mocker.patch.object(staging_instance, "process_rspy_features", return_value=True)
        # Simulate an already running event loop
        mocker.patch.object(asyncio, "get_event_loop", return_value=asyncio_loop)
        mocker.patch.object(asyncio_loop, "is_running", return_value=True)

        # Call the async execute method
        result = await staging_instance.execute(staging_inputs)

        # Assertions
        assert spy_log_job.call_count == 1
        spy_log_job.assert_has_calls(
            [call(JobStatus.running, 0, "Successfully searched catalog")],
        )
        mock_check_catalog.assert_called_once()
        mock_process_rspy.assert_called_once()  # Ensures processing is scheduled
        assert result == ("application/json", {"running": staging_instance.job_id})

    @pytest.mark.asyncio
    async def test_execute_fails_in_checking_catalog(
        self,
        mocker,
        staging_instance: Staging,
        staging_inputs: dict,
        asyncio_loop,
    ):
        """Test execute method while a asyncio loop is running"""
        spy_log_job = mocker.spy(staging_instance, "log_job_execution")
        mock_check_catalog = mocker.patch.object(staging_instance, "check_catalog", return_value=False)
        # Simulate an already running event loop
        mocker.patch.object(asyncio, "get_event_loop", return_value=asyncio_loop)
        mocker.patch.object(asyncio_loop, "is_running", return_value=True)

        # Call the async execute method
        result = await staging_instance.execute(staging_inputs)

        # Assertions
        assert spy_log_job.call_count == 1
        spy_log_job.assert_has_calls(
            [
                call(
                    JobStatus.failed,
                    0,
                    "Failed to start the staging process. Checking the collection 'test_collection' failed !",
                ),
            ],
        )
        mock_check_catalog.assert_called_once()

        assert result == ("application/json", {"failed": staging_instance.job_id})

    @pytest.mark.asyncio
    async def test_execute_with_running_loop_without_item_collection(
        self,
        mocker,
        staging_instance: Staging,
        asyncio_loop,
    ):
        """Test execute method while a asyncio loop is running"""
        spy_log_job = mocker.spy(staging_instance, "log_job_execution")

        # Simulate an already running event loop
        mocker.patch.object(asyncio, "get_event_loop", return_value=asyncio_loop)
        mocker.patch.object(asyncio_loop, "is_running", return_value=True)

        # Call the async execute method
        result = await staging_instance.execute(data={"collection": "test_collection"})

        # Assertions
        spy_log_job.assert_called_once_with(
            JobStatus.successful,
            0,
            "No valid items were provided in the input for staging",
        )
        assert result == ("application/json", {"successful": staging_instance.job_id})

    def test_create_job_execution(self, staging_instance: Staging, mocker):
        """Test the create_job_execution method of the Staging class.

        This test verifies that the create_job_execution method correctly inserts a new job execution
        entry into the db_process_manager with the current job's attributes.

        Args:
            staging_instance (Staging): An instance of the Staging class, pre-initialized for testing.
            mocker (pytest_mock.MockerFixture): The mocker fixture to patch methods and objects during tests.

        """
        # create mock object of self.db_process_manager and overwrite staging instance from conftest
        mock_db_process_manager = mocker.Mock()
        staging_instance.db_process_manager = mock_db_process_manager

        # Set job attributes needed for create_job_execution
        staging_instance.job_id = "12345"
        staging_instance.status = JobStatus.accepted
        staging_instance.progress = 0
        staging_instance.message = "Job is starting."

        # Call the method to test if self attrs are written into db
        staging_instance.create_job_execution()

        # Assert that the insert method was called once with the expected arguments
        mock_db_process_manager.add_job.assert_called_once_with(
            {
                "identifier": "12345",
                "processID": "staging",
                "status": JobStatus.accepted.value,
                "progress": 0,
                "message": "Job is starting.",
            },
        )

    def test_log_job_execution(self, staging_instance: Staging, mocker):
        """Test the log_job_execution method of the Staging class.

        This test verifies that the log_job_execution method correctly updates the job's status,
        progress, and message in the db_process_manager database, both for default and custom attributes.

        Args:
            staging_instance (Staging): An instance of the Staging class, pre-initialized for testing.
            mocker (pytest_mock.MockerFixture): The mocker fixture to patch methods and objects during tests.

        """
        # Mock self.db_process_manager and self.lock attrs
        mock_db_process_manager = mocker.Mock()

        staging_instance.db_process_manager = mock_db_process_manager
        staging_instance.job_id = "12345"
        staging_instance.status = JobStatus.accepted
        staging_instance.progress = 0
        staging_instance.message = "Job is starting."

        # Mock the update method of the db_process_manager
        mock_update_job = mocker.patch.object(staging_instance.db_process_manager, "update_job", return_value=None)

        # Mock datetime
        fake_now = datetime(2024, 1, 1, 12, 0, 0)
        mock_datetime = mocker.patch("rs_server_staging.processors.datetime")
        mock_datetime.now.return_value = fake_now

        # Call log_job_execution to test status update with default attrs
        staging_instance.log_job_execution()

        # Assert that the update method was called with the correct parameters
        mock_update_job.assert_called_once_with(
            staging_instance.job_id,
            {
                "status": JobStatus.accepted.value,
                "progress": 0,
                "message": "Job is starting.",
                "updated": fake_now,
            },
        )

        # reset the mock called counter
        mock_update_job.reset_mock()

        # Call log_job_execution to test status update with custom attrs
        staging_instance.log_job_execution(
            JobStatus.running,
            50.0,  # type: ignore
            "Job is halfway done.",
        )

        # Assert that the update method was called with the custom parameters
        mock_update_job.assert_called_once_with(
            staging_instance.job_id,
            {
                "status": JobStatus.running.value,
                "progress": 50.0,
                "message": "Job is halfway done.",
                "updated": fake_now,
            },
        )


class TestStagingCatalog:
    """Group of all tests used for method that search the catalog before processing."""

    def _call_check_catalog(self, staging_instance: Staging, staging_inputs: dict):
        return staging_instance.check_catalog(
            staging_inputs["collection"],
            FeatureCollectionModel.parse_obj(staging_inputs["items"]["value"]).features,
        )

    @pytest.mark.asyncio
    async def test_check_catalog_success(self, mocker, staging_instance: Staging, staging_inputs: dict):
        """Test the check_catalog method for successful execution.

        This test verifies that the check_catalog method correctly formats the request
        to the catalog URL and handles the response appropriately.

        Args:
            mocker: The mocker fixture to patch methods and objects during tests.
            staging_instance (Staging): An instance of the Staging class, pre-initialized for testing.
        """
        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        # mock all other called methods
        mock_create_streaming_list = mocker.patch.object(staging_instance, "create_streaming_list", return_value=None)
        mock_log_job_execution = mocker.patch.object(staging_instance, "log_job_execution", return_value=None)

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"type": "FeatureCollection", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mocker.patch("requests.get", return_value=mock_response)

        # Call the method under test
        result = await self._call_check_catalog(staging_instance, staging_inputs)

        # Assert that the result is True (successful catalog check)
        assert result is True

        # Construct the expected filter string
        expected_filter_object = {
            "collections": "test_collection",
            "filter-lang": "cql2-text",
            "filter": "id IN ('1', '2')",
            "limit": "2",
        }
        # Assert that requests.get was called with the correct parameters
        requests.get.assert_called_once_with(  # type: ignore
            f"{staging_instance.catalog_url}/catalog/search",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
            params=expected_filter_object,
            timeout=5,
        )
        mock_create_streaming_list.called_once()
        mock_log_job_execution.called_once()

    @pytest.mark.asyncio
    async def test_check_catalog_get_wrong_response(self, mocker, staging_instance: Staging, staging_inputs: dict):
        """docstring to be added"""
        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"wrong_key": "Unknown_test", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mocker.patch("requests.get", return_value=mock_response)

        # Call the method under test
        result = await self._call_check_catalog(staging_instance, staging_inputs)

        # Assert that the result is True (successful catalog check)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_catalog_failure(self, mocker, staging_instance: Staging, staging_inputs: dict):
        """docstring to be added"""
        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        # Loop trough all possible exception raised during request.get and check if failure happen
        for possible_exception in [
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
        ]:
            # mock all other called methods
            mock_log_job_execution = mocker.patch.object(staging_instance, "log_job_execution", return_value=None)

            get_err_msg = "HTTP Error msg"
            mocker.patch("requests.get", side_effect=possible_exception(get_err_msg))

            # Mock the create_streaming_list method
            mock_create_streaming_list = mocker.patch.object(staging_instance, "create_streaming_list")

            # Call the method under test
            result = await self._call_check_catalog(staging_instance, staging_inputs)

            # Assert that the result is False (failed catalog check)
            assert result is False

            # Assert that create_streaming_list was not called during failure
            mock_create_streaming_list.assert_not_called()
            mock_log_job_execution.assert_called_once_with(
                JobStatus.failed,
                0,
                f"Failed to search catalog: {get_err_msg}",
            )

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"type": "FeatureCollection", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mock_log_job_execution = mocker.patch.object(staging_instance, "log_job_execution", return_value=None)
        mocker.patch("requests.get", return_value=mock_response)
        err_msg = "RE test msg"
        mocker.patch.object(
            staging_instance,
            "create_streaming_list",
            side_effect=RuntimeError(err_msg),
        )
        # Call the method under test
        await self._call_check_catalog(staging_instance, staging_inputs)
        mock_log_job_execution.assert_called_once_with(
            JobStatus.failed,
            0,
            f"Failed to search catalog: {err_msg}",
        )


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
            ("https://example.com/asset1", f"{catalog_collection}/{feature.id}/asset1"),
            ("https://example.com/asset2", f"{catalog_collection}/{feature.id}/asset2"),
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


class TestStagingDeleteFromBucket:
    """Class used to group tests that handle file bucket removal if failure"""

    def test_delete_files_from_bucket_succes(self, mocker, staging_instance: Staging):
        """Test all files were removed from given bucket"""
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "fake_endpoint",
                "S3_REGION": "fake_region",
            },
        )
        # Mock the assets_info to simulate a list of assets
        staging_instance.assets_info = [("fake_asset_href", "fake_s3_path")]
        # Mock S3StorageHandler and its delete_file_from_s3 method
        mock_s3_handler = mocker.Mock()
        mocker.patch("rs_server_staging.processors.S3StorageHandler", return_value=mock_s3_handler)
        # Call the delete_files_from_bucket method
        staging_instance.delete_files_from_bucket()
        # Assert that S3StorageHandler was instantiated with the correct environment variables
        mock_s3_handler.delete_file_from_s3.assert_called_once_with("fake_bucket", "fake_s3_path")

    def test_delete_files_from_bucket_empty(self, mocker, staging_instance: Staging):
        """Test delete files with no assets, nothing should happen."""
        staging_instance.assets_info = []
        # Mock S3StorageHandler to ensure it's not used
        mock_s3_handler = mocker.Mock()
        mocker.patch("rs_server_staging.processors.S3StorageHandler", return_value=mock_s3_handler)
        # Call the method
        staging_instance.delete_files_from_bucket()
        # Assert that delete_file_from_s3 was never called since there are no assets
        mock_s3_handler.delete_file_from_s3.assert_not_called()

    def test_delete_files_from_bucket_failed_to_create_s3_handler(self, mocker, staging_instance: Staging):
        """Test a failure in creating s3 storage handler."""
        # Mock the environment variables but leave one out to trigger KeyError
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "fake_endpoint",
                # "S3_REGION" is missing to trigger KeyError
            },
        )
        # Mock assets_info
        staging_instance.assets_info = [("fake_asset_href", "fake_s3_path")]
        # Mock the logger to check if the error is logged
        mock_logger = mocker.patch.object(staging_instance, "logger")
        # Call the method and expect it to handle KeyError
        staging_instance.delete_files_from_bucket()
        # Assert that the error was logged
        mock_logger.error.assert_called_once_with("Cannot connect to s3 storage, %s", mocker.ANY)

    def test_delete_files_from_bucket_fail_while_in_progress(self, mocker, staging_instance: Staging):
        """Test a runtime error while using s3_handler.delete_file_from_s3, should produce a logger error,
        nothing else?
        """
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "fake_endpoint",
                "S3_REGION": "fake_region",
            },
        )
        # Mock assets_info
        staging_instance.assets_info = [("fake_asset_href", "fake_s3_path")]
        # Mock S3StorageHandler and raise a RuntimeError
        mock_s3_handler = mocker.Mock()
        mock_s3_handler.delete_file_from_s3.side_effect = RuntimeError("Fake runtime error")
        mocker.patch("rs_server_staging.processors.S3StorageHandler", return_value=mock_s3_handler)
        # Mock the logger to verify error handling
        mock_logger = mocker.patch.object(staging_instance, "logger")
        # Call the method and expect it to handle RuntimeError
        staging_instance.delete_files_from_bucket()
        # Assert that the error was logged
        mock_logger.warning.assert_called()


class TestStagingMainExecution:
    """Class to test Item processing"""

    def test_dask_cluster_connect(
        self,
        mocker,
        staging_instance: Staging,
        cluster,
    ):  # pylint: disable=R0913, R0917
        """Test to mock the connection to a dask cluster"""
        # Mock environment variables to simulate gateway mode
        mocker.patch.dict(
            os.environ,
            {
                "DASK_GATEWAY__ADDRESS": "gateway-address",
                "DASK_GATEWAY__AUTH__TYPE": "jupyterhub",
                "JUPYTERHUB_API_TOKEN": "mock_api_token",
                "RSPY_DASK_STAGING_CLUSTER_NAME": str(
                    cluster.options.get("cluster_name", "default_cluster"),
                ),  # type: ignore
            },
        )
        # Mock the cluster mode
        mocker.patch("rs_server_common.settings.LOCAL_MODE", new=False, autospec=False)
        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        staging_instance.cluster = None
        # Mock the JupyterHubAuth, Gateway, and Client classes
        mock_list_clusters = mocker.patch.object(Gateway, "list_clusters")
        mock_connect = mocker.patch.object(Gateway, "connect")
        mock_client = mocker.patch("rs_server_staging.processors.Client", autospec=True, return_value=None)

        mock_list_clusters.return_value = [cluster]
        mock_connect.return_value = cluster

        # Setup client mock
        mock_scheduler_info: dict[str, dict] = {"workers": {"worker-1": {}, "worker-2": {}}}
        mock_client_instance = mocker.Mock()
        mock_client_instance.scheduler_info.return_value = mock_scheduler_info
        mock_client.return_value = mock_client_instance

        # Call the method under test
        client = staging_instance.dask_cluster_connect()

        # assertions
        mock_list_clusters.assert_called_once()
        mock_connect.assert_called_once_with("dask-gateway-id")
        mock_client.assert_called_once_with(staging_instance.cluster)

        # Ensure logging was called as expected
        mock_logger.debug.assert_any_call(
            f"Cluster list for gateway 'gateway-address': {mock_list_clusters.return_value}",
        )
        mock_logger.info.assert_any_call("Number of running workers: 2")
        mock_logger.debug.assert_any_call(
            f"Dask Client: {client} | Cluster dashboard: {mock_connect.return_value.dashboard_link}",
        )

    def test_dask_cluster_connect_failure_no_cluster_name(
        self,
        mocker,
        staging_instance: Staging,
        cluster,
    ):
        """Test the bahavior in case no cluster name is found"""
        non_existent_cluster = "another-cluster-name"
        # Mock environment variables to simulate gateway mode
        mocker.patch.dict(
            os.environ,
            {
                "DASK_GATEWAY__ADDRESS": "gateway-address",
                "DASK_GATEWAY__AUTH__TYPE": "jupyterhub",
                "JUPYTERHUB_API_TOKEN": "mock_api_token",
                "RSPY_DASK_STAGING_CLUSTER_NAME": non_existent_cluster,
            },
        )
        # Mock the cluster mode
        mocker.patch("rs_server_common.settings.LOCAL_MODE", new=False, autospec=False)
        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        staging_instance.cluster = None
        # Mock the JupyterHubAuth, Gateway, and Client classes
        mock_list_clusters = mocker.patch.object(Gateway, "list_clusters")
        mock_connect = mocker.patch.object(Gateway, "connect")

        mock_list_clusters.return_value = [cluster]
        mock_connect.return_value = cluster

        with pytest.raises(RuntimeError):
            staging_instance.dask_cluster_connect()
        # Ensure logging was called as expected
        mock_logger.exception.assert_any_call(
            "Failed to find the specified dask cluster: "
            f"Dask cluster with 'cluster_name'={non_existent_cluster!r} was not found.",
        )

    def test_dask_cluster_connect_failure_no_envs(
        self,
        mocker,
        staging_instance: Staging,
    ):
        """Test to mock the connection to a dask cluster"""
        # Not all the needed env vars are mocked
        mocker.patch.dict(
            os.environ,
            {
                "DASK_GATEWAY__ADDRESS": "gateway-address",
            },
        )

        staging_instance.cluster = None
        with pytest.raises(RuntimeError):
            staging_instance.dask_cluster_connect()

    def test_manage_dask_tasks_succesfull(self, mocker, staging_instance: Staging, client):
        """Test to mock managing of successul tasks"""
        # Mock tasks that will succeed
        task1 = mocker.Mock()
        task1.result = mocker.Mock(return_value="simultated_filename_1")  # Simulate a successful task
        task1.key = "task1"

        task2 = mocker.Mock()
        task2.result = mocker.Mock(return_value="simultated_filename_2")  # Simulate another successful task
        task2.key = "task2"

        # mock distributed as_completed
        mocker.patch("rs_server_staging.processors.as_completed", return_value=iter([task1, task2]))
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mock_publish_feature = mocker.patch.object(staging_instance, "publish_rspy_feature")

        staging_instance.manage_dask_tasks(client, "test_collection", staging_instance.station_token_list[0])

        # mock_log_job.assert_any_call(JobStatus.running, None, 'In progress')
        # Check that status was updated 3 times during execution, 1 time for each task, and 1 time with FINISH
        mock_log_job.assert_any_call(JobStatus.successful, 100, "Finished")
        assert mock_log_job.call_count == 3
        # Check that feature publish method was called.
        mock_publish_feature.assert_called()

    def test_manage_dask_tasks_failure(self, mocker, staging_instance: Staging, client):
        """Test handling callbacks when error on one task"""
        task1 = mocker.Mock()
        # Simulate a exception in task
        task1.result = mocker.Mock(return_value=None, side_effect=Exception("Fake exception"))
        task1.key = "task1"
        task2 = mocker.Mock()
        # Simulate another successful task
        task2.result = mocker.Mock(return_value="simultated_filename_2")
        task2.key = "task2"

        # Create mock for task, and distributed.as_completed func
        mocker.patch("rs_server_staging.processors.as_completed", return_value=iter([task1, task2]))
        # Create mock for handle_task_failure, publish_rspy_feature, delete_files_from_bucket, log_job_execution methods
        mock_publish_feature = mocker.patch.object(staging_instance, "publish_rspy_feature")
        mock_delete_file_from_bucket = mocker.patch.object(staging_instance, "delete_files_from_bucket")
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        # Mock the cancel and call_stack function from dask client
        client.cancel = mocker.Mock(return_value=None)
        client.call_stack = mocker.Mock(return_value=None)
        # Set timeout to 1, thus the waiting logic for dask client call_stack will loop once only
        mocker.patch.dict("os.environ", {"RSPY_STAGING_TIMEOUT": "1"})

        staging_instance.manage_dask_tasks(client, "test_collection", staging_instance.station_token_list[0])

        mock_delete_file_from_bucket.assert_called()  # Bucket removal called once
        # logger set status to failed
        mock_log_job.assert_called_once_with(JobStatus.failed, None, "At least one of the tasks failed: Fake exception")
        # Features are not published here.
        mock_publish_feature.assert_not_called()

    def test_manage_dask_tasks_failed_to_publish(self, mocker, staging_instance: Staging, client):
        """Test to mock managing of successul tasks"""
        # Mock tasks that will succeed
        task1 = mocker.Mock()
        task1.result = mocker.Mock(return_value="simultated_filename_1")  # Simulate a successful task
        task1.key = "task1"

        task2 = mocker.Mock()
        task2.result = mocker.Mock(return_value="simultated_filename_2")  # Simulate another successful task
        task2.key = "task2"

        staging_instance.stream_list = [task1, task2]  # set streaming list
        # mock distributed as_completed
        mocker.patch("rs_server_staging.processors.as_completed", return_value=iter([task1, task2]))
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")

        mocker.patch.object(staging_instance, "publish_rspy_feature", return_value=False)
        mock_delete_file_from_bucket = mocker.patch.object(staging_instance, "delete_files_from_bucket")

        staging_instance.manage_dask_tasks(client, "test_collection", staging_instance.station_token_list[0])

        mock_log_job.assert_any_call(
            JobStatus.failed,
            None,
            f"The item {task1.id} couldn't be published in the catalog. Cleaning up",
        )
        mock_delete_file_from_bucket.assert_called()

    def test_manage_dask_tasks_no_dask_client(self, mocker, staging_instance: Staging):
        """Test the manage_dask_tasks when no valid dask client is received"""
        mock_logger = mocker.patch.object(staging_instance, "logger")
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")

        staging_instance.manage_dask_tasks(None, "test_collection", staging_instance.station_token_list[0])
        mock_logger.error.assert_called_once_with("The dask cluster client object is not created. Exiting")
        mock_log_job.assert_any_call(
            JobStatus.failed,
            None,
            "Submitting task to dask cluster failed. Dask cluster client object is not created",
        )

    @pytest.mark.asyncio
    async def test_process_rspy_features_empty_assets(self, mocker, staging_instance: Staging):
        """Test that process_rspy_features handles task preparation failure."""

        # Mock dependencies
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=False)

        # Set stream_list with one feature (to trigger task preparation)
        mock_feature = mocker.Mock()
        staging_instance.stream_list = [mock_feature]

        # Call the method
        await staging_instance.process_rspy_features("test_collection")

        # Ensure the task preparation failed, and method returned early
        mock_log_job.assert_called_with(JobStatus.failed, 0, "Unable to create tasks for the Dask cluster")

    @pytest.mark.asyncio
    async def test_process_rspy_features_empty_stream(self, mocker, staging_instance: Staging):
        """Test that process_rspy_features logs the initial setup and starts the main loop."""

        # Mock dependencies
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=True)

        # Set the assets_info to an empty list (no features to process)
        staging_instance.assets_info = []

        # Call the method
        await staging_instance.process_rspy_features("test_collection")

        # Assert initial logging and job execution calls
        mock_log_job.assert_called_with(JobStatus.successful, 100, "Finished without processing any tasks")

    @pytest.mark.asyncio
    async def test_process_rspy_features_dask_connection_failure(
        self,
        mocker,
        staging_instance: Staging,
    ):
        """Test case where connecting to the Dask cluster raises a RuntimeError."""
        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        # Simulate successful task preparation
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=True)
        staging_instance.assets_info = ["some_asset"]

        # Mock token retrieval
        mocker.patch(
            "rs_server_staging.processors.load_external_auth_config_by_domain",
            return_value=mocker.Mock(),
        )
        mocker.patch(
            "rs_server_common.authentication.token_auth.get_station_token",
            return_value="mock_token",
        )

        # Simulate a RuntimeError during Dask cluster connection
        mocker.patch.object(
            staging_instance,
            "dask_cluster_connect",
            side_effect=RuntimeError("Dask cluster client failed"),
        )
        # Mock manage_dask_tasks
        mock_manage_dask_tasks = mocker.patch.object(staging_instance, "manage_dask_tasks")

        # Call the async function
        await staging_instance.process_rspy_features("test_collection")

        # Verify log_job_execution is called with the error details
        mock_log_job.assert_called_once_with(JobStatus.failed, 0, "Dask cluster client failed")
        mock_logger.error.assert_called_once_with("Failed to start the staging process")

        # Verify that the monitoring thread is not executed
        mock_manage_dask_tasks.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_rspy_features_success(
        self,
        mocker,
        staging_instance: Staging,
        client,
        config,
    ):
        """Test case where the entire process runs successfully."""
        mocker.patch.dict(
            os.environ,
            {
                "DASK_GATEWAY__ADDRESS": "gateway-address",
                "DASK_GATEWAY__AUTH__TYPE": "jupyterhub",
                "JUPYTERHUB_API_TOKEN": "mock_api_token",
                "RSPY_DASK_STAGING_CLUSTER_NAME": str(
                    client.cluster.options.get("cluster_name", "default_cluster"),
                ),  # type: ignore
            },
        )
        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        mocker.patch.object(staging_instance, "log_job_execution")
        # Simulate successful task preparation
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=True)

        # Mock token retrieval
        mocker.patch(
            "rs_server_staging.processors.load_external_auth_config_by_domain",
            return_value=mocker.Mock(),
        )

        # Mock the external auth configuration
        config.trusted_domains = ["test_trusted.example"]  # Set the trusted_domains member
        mocker.patch(
            "rs_server_staging.processors.load_external_auth_config_by_domain",
            return_value=config,
        )

        # Mock Dask cluster client
        mocker.patch.object(staging_instance, "dask_cluster_connect", return_value=client)

        # Mock update_station_token
        mocker.patch(
            "rs_server_staging.processors.update_station_token",
            return_value=True,
        )

        # Mock manage_dask_tasks
        mock_manage_dask_tasks = mocker.patch.object(staging_instance, "manage_dask_tasks")

        # Call the async function
        await staging_instance.process_rspy_features("test_collection")

        # Verify the task monitoring thread is started
        mock_logger.debug.assert_any_call("Starting tasks monitoring thread")
        mock_manage_dask_tasks.assert_called_once_with(
            client,
            "test_collection",
            staging_instance.station_token_list[0],
        )

        # Ensure the Dask client is closed after the tasks are processed
        client.close.assert_called_once()

        # Verify assets_info is cleared after processing
        assert staging_instance.assets_info == []


class TestStagingPublishCatalog:
    """Class to group tests for catalog publishing after streaming was processes"""

    def test_publish_rspy_feature_success(self, mocker, staging_instance: Staging):
        """Test successful feature publishing to the catalog."""
        feature = mocker.Mock()  # Mock the feature object
        feature.json.return_value = '{"id": "feature1", "properties": {"name": "test"}}'  # Mock the JSON serialization
        feature.assets = {}

        # Mock requests.post to return a successful response
        mock_response = mocker.Mock()
        mock_response.raise_for_status.return_value = None  # No error
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        result = staging_instance.publish_rspy_feature("test_collection", feature)

        assert result is True  # Should return True for successful publishing
        mock_post.assert_called_once_with(
            f"{staging_instance.catalog_url}/catalog/collections/test_collection/items",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
            data=feature.json(),
            timeout=10,
        )
        feature.json.assert_called()  # Ensure the feature JSON serialization was called

    def test_publish_rspy_feature_fail(self, mocker, staging_instance: Staging):
        """Test failure during feature publishing and cleanup on error."""
        feature = mocker.Mock()
        feature.json.return_value = '{"id": "feature1", "properties": {"name": "test"}}'
        feature.assets = {}

        for possible_exception in [
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
        ]:
            # Mock requests.post to raise an exception
            mock_post = mocker.patch("requests.post", side_effect=possible_exception("HTTP Error occurred"))

            # Mock the logger and other methods called on failure
            mock_logger = mocker.patch.object(staging_instance, "logger")

            result = staging_instance.publish_rspy_feature("test_collection", feature)

            assert result is False  # Should return False for failure
            mock_post.assert_called_once_with(
                f"{staging_instance.catalog_url}/catalog/collections/test_collection/items",
                headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
                data=feature.json(),
                timeout=10,
            )
            mock_logger.error.assert_called_once_with("Error while publishing items to rspy catalog %s", mocker.ANY)

    def test_repr(self, staging_instance: Staging):
        """Test repr method for coverage"""
        assert repr(staging_instance) == "RSPY Staging OGC API Processor"


class TestStagingUnpublishCatalog:
    """Class to group tests for catalog unpublishing after streaming failed"""

    def test_unpublish_rspy_features_success(self, mocker, staging_instance: Staging):
        """Test successful unpublishing feature ids to the catalog."""
        feature_ids = ["feature-1", "feature-2"]
        mock_logger = mocker.patch.object(staging_instance, "logger")

        # Mock requests.delete to return a successful response

        mock_delete = mocker.patch("requests.delete")
        mock_delete.return_value.status_code = 200

        staging_instance.unpublish_rspy_features("test_collection", feature_ids)

        # Assert that delete was called with the correct URL and headers
        mock_delete.assert_any_call(
            f"{staging_instance.catalog_url}/catalog/collections/test_collection/items/feature-1",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
            timeout=3,
        )
        mock_delete.assert_any_call(
            f"{staging_instance.catalog_url}/catalog/collections/test_collection/items/feature-2",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
            timeout=3,
        )
        # Ensure no error was logged
        mock_logger.error.assert_not_called()

    def test_unpublish_rspy_features_fail(self, mocker, staging_instance: Staging):
        """Test failure during feature unpublishing ."""
        feature_ids = ["feature-1"]

        for possible_exception in [
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
        ]:
            # Mock requests.post to raise an exception
            mock_delete = mocker.patch("requests.delete", side_effect=possible_exception("HTTP Error occurred"))

            # Mock the logger and other methods called on failure
            mock_logger = mocker.patch.object(staging_instance, "logger")

            staging_instance.unpublish_rspy_features("test_collection", feature_ids)

            mock_delete.assert_any_call(
                f"{staging_instance.catalog_url}/catalog/collections/test_collection/items/feature-1",
                headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
                timeout=3,
            )
            mock_logger.error.assert_called_once_with("Error while deleting the item from rspy catalog %s", mocker.ANY)

    def test_repr(self, staging_instance: Staging):
        """Test repr method for coverage"""
        assert repr(staging_instance) == "RSPY Staging OGC API Processor"


# Disabled for moment
# class TestStagingDaskSerialization:
#     def test_pickle_serialization(staging_instance):
#         """
#         Test if an instance of the class is pickle serializable.
#         """
#         import pickle
#         def remove_mocks(obj):
#             """
#             Recursively remove mock objects from an instance's __dict__.
#             """
#             # Both for unittests and pytests mocker
#             from unittest.mock import Mock

#             for key, value in list(obj.__dict__.items()):
#                 if isinstance(value, Mock):
#                     setattr(obj, key, None)  # Replace mock with None or a dummy value
#                 elif isinstance(value, dict):
#                     # Recursively remove mocks from nested dictionaries
#                     for sub_key, sub_value in list(value.items()):
#                         if isinstance(sub_value, Mock):
#                             value[sub_key] = None
#                 elif hasattr(value, "__dict__"):
#                     # Recursively remove mocks from nested objects
#                     remove_mocks(value)

#         # Clean mocks from the instance
#         remove_mocks(staging_instance)

#         # Try to serialize the instance
#         try:
#             pickled_data = pickle.dumps(staging_instance)
#         except pickle.PicklingError:
#             pytest.fail("Pickle serialization failed.")

#         # Try to deserialize the instance
#         try:
#             unpickled_instance = pickle.loads(pickled_data)
#         except Exception as e:
#             pytest.fail(f"Pickle deserialization failed: {e}")

#         # Optional: You can add more checks to ensure the instance is correctly restored
#         assert isinstance(unpickled_instance, type(staging_instance)), "Unpickled instance
#  is not of the correct type."
