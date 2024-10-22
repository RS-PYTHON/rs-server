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

"""Test module for RSPYStaging processor."""
import asyncio

# import json
import os
import threading
from unittest.mock import call

import pytest
import requests

# from dask.distributed import Client
# from dask_gateway import Gateway
# from dask_gateway.auth import JupyterHubAuth
from rs_server_staging.processors import ProcessorStatus, TokenAuth, streaming_download

# pylint: disable=undefined-variable
# pylint: disable=no-member


class TestProcessorStatus:
    """."""

    def test_str_method(self):
        """Test the __str__ method of ProcessorStatus."""
        assert str(ProcessorStatus.QUEUED) == "queued"
        assert str(ProcessorStatus.FINISHED) == "finished"
        assert str(ProcessorStatus.FAILED) == "failed"

    def test_to_json_valid(self):
        """Test the to_json method for valid ProcessorStatus instances."""
        assert ProcessorStatus.to_json(ProcessorStatus.QUEUED) == "queued"
        assert ProcessorStatus.to_json(ProcessorStatus.FINISHED) == "finished"
        assert ProcessorStatus.to_json(ProcessorStatus.STARTED) == "started"

    def test_to_json_invalid(self):
        """Test the to_json method for invalid values (non-ProcessorStatus)."""
        with pytest.raises(ValueError):
            ProcessorStatus.to_json("invalid_status")  # Should raise a ValueError
        with pytest.raises(ValueError):
            ProcessorStatus.to_json(123)  # Should raise a ValueError
        with pytest.raises(ValueError):
            ProcessorStatus.to_json(None)  # Should raise a ValueError

    def test_from_json_valid(self):
        """Test the from_json method for valid status strings."""
        assert ProcessorStatus.from_json("queued") == ProcessorStatus.QUEUED
        assert ProcessorStatus.from_json("finished") == ProcessorStatus.FINISHED
        assert ProcessorStatus.from_json("started") == ProcessorStatus.STARTED

    def test_from_json_invalid(self):
        """Test the from_json method for invalid status strings."""
        with pytest.raises(ValueError):
            ProcessorStatus.from_json("invalid_status")  # Should raise a ValueError
        with pytest.raises(ValueError):
            ProcessorStatus.from_json("not_a_status")  # Should raise a ValueError
        with pytest.raises(ValueError):
            ProcessorStatus.from_json(None)  # Should raise a ValueError


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
        assert modified_request.headers["Content-Type"] == "application/x-www-form-urlencoded"

    def test_token_auth_repr(self):
        """Test the repr_ method of TokenAuth."""
        auth = TokenAuth("my_test_token")
        assert repr(auth) == "RSPY Token handler"


def test_streaming_download_incorrect_env(mocker):
    """Test a error while creating s3 handler"""
    # mock init of s3 handler without S3_ACCESSKEY, should raise an error while creating s3 handler
    mocker.patch.dict(
        "os.environ",
        {"S3_SECRETKEY": "fake_secret_key", "S3_ENDPOINT": "fake_endpoint", "S3_REGION": "fake_region"},
    )
    with pytest.raises(ValueError, match=r"Cannot create s3 connector object."):
        streaming_download("https://example.com/product.zip", "Bearer token", "bucket", "file.zip")


def test_streaming_download_runtime_error(mocker):
    """Test a runtimeerror while streaming-download."""
    mocker.patch.dict(
        "os.environ",
        {
            "S3_ACCESSKEY": "fake_access_key",
            "S3_SECRETKEY": "fake_secret_key",
            "S3_ENDPOINT": "fake_endpoint",
            "S3_REGION": "fake_region",
        },
    )

    # mock inner s3_handler.streaming to raise
    mocker.patch(
        "rs_server_staging.processors.S3StorageHandler.s3_streaming_upload",
        side_effect=RuntimeError("Streaming failed"),
    )
    # If s3-streaming raise runtime error, we forward value error? to be checked
    with pytest.raises(
        ValueError,
        match=r"Dask task failed to stream file from " r"https://example.com/product.zip to s3://bucket/file.zip",
    ):
        streaming_download("https://example.com/product.zip", "Bearer token", "bucket", "file.zip")


class TestRSPYStaging:
    """Test class for RSPYStaging processor"""

    @pytest.mark.asyncio
    async def test_execute_with_running_loop(self, mocker, staging_instance, asyncio_loop):
        """Test execute method while a asyncio loop is running"""
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mock_check_catalog = mocker.patch.object(staging_instance, "check_catalog", return_value=True)
        mock_process_rspy = mocker.patch.object(staging_instance, "process_rspy_features", return_value=True)

        # Simulate an already running event loop
        mocker.patch.object(asyncio, "get_event_loop", return_value=asyncio_loop)
        mocker.patch.object(asyncio_loop, "is_running", return_value=True)

        # Call the async execute method
        result = await staging_instance.execute()

        # Assertions
        assert mock_log_job.call_count == 2
        mock_log_job.assert_has_calls(
            [call(ProcessorStatus.CREATED), call(ProcessorStatus.STARTED, 0, detail="Successfully searched catalog")],
        )
        mock_check_catalog.assert_called_once()
        mock_process_rspy.assert_called_once()  # Ensures processing is scheduled
        assert result == {"started": staging_instance.job_id}

    @pytest.mark.asyncio
    async def test_execute_with_running_loop_without_item_collection(self, mocker, staging_instance, asyncio_loop):
        """Test execute method while a asyncio loop is running"""
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")

        # Simulate an already running event loop
        mocker.patch.object(asyncio, "get_event_loop", return_value=asyncio_loop)
        mocker.patch.object(asyncio_loop, "is_running", return_value=True)

        # set item_collection to None
        staging_instance.item_collection = None

        # Call the async execute method
        result = await staging_instance.execute()

        # Assertions
        mock_log_job.assert_called_once_with(
            ProcessorStatus.FINISHED,
            0,
            detail="No items were provided in the input for staging",
        )
        assert result == {"finished": staging_instance.job_id}

    def test_create_job_execution(self, staging_instance, mocker):
        """Test the create_job_execution method of the RSPYStaging class.

        This test verifies that the create_job_execution method correctly inserts a new job execution
        entry into the tracker with the current job's attributes.

        Args:
            staging_instance (RSPYStaging): An instance of the RSPYStaging class, pre-initialized for testing.
            mocker (pytest_mock.MockerFixture): The mocker fixture to patch methods and objects during tests.

        """
        # create mock object of self.tracker and overwrite staging instance from conftest
        mock_tracker = mocker.Mock()
        staging_instance.tracker = mock_tracker

        # Set job attributes needed for create_job_execution
        staging_instance.job_id = "12345"
        staging_instance.status = ProcessorStatus.QUEUED
        staging_instance.progress = 0
        staging_instance.detail = "Job is starting."

        # Call the method to test if self attrs are written into db
        staging_instance.create_job_execution()

        # Assert that the insert method was called once with the expected arguments
        mock_tracker.insert.assert_called_once_with(
            {
                "job_id": "12345",
                "status": ProcessorStatus.to_json(ProcessorStatus.QUEUED),
                "progress": 0,
                "detail": "Job is starting.",
            },
        )

    def test_log_job_execution(self, staging_instance, mocker):
        """Test the log_job_execution method of the RSPYStaging class.

        This test verifies that the log_job_execution method correctly updates the job's status,
        progress, and detail in the tracker database, both for default and custom attributes.

        Args:
            staging_instance (RSPYStaging): An instance of the RSPYStaging class, pre-initialized for testing.
            mocker (pytest_mock.MockerFixture): The mocker fixture to patch methods and objects during tests.

        """
        # Mock self.tracker and self.lock attrs
        mock_tracker = mocker.Mock()
        staging_instance.lock = threading.Lock()

        staging_instance.tracker = mock_tracker
        staging_instance.job_id = "12345"
        staging_instance.status = ProcessorStatus.QUEUED
        staging_instance.progress = 0
        staging_instance.detail = "Job is starting."

        # Mock the update method of the tracker
        mock_update_default = mocker.patch.object(staging_instance.tracker, "update", return_value=None)

        # Call log_job_execution to test status update with default attrs
        staging_instance.log_job_execution()

        # Assert that the update method was called with the correct parameters
        mock_update_default.assert_called_once_with(
            {"status": ProcessorStatus.to_json(ProcessorStatus.QUEUED), "progress": 0, "detail": "Job is starting."},
            mocker.ANY,
        )
        mock_update_custom = mocker.patch.object(staging_instance.tracker, "update", return_value=None)
        mock_query = mocker.patch("tinydb.Query", return_value=mocker.Mock())
        # Call log_job_execution to test status update with custom attrs
        staging_instance.log_job_execution(
            status=ProcessorStatus.IN_PROGRESS,
            progress=50.0,
            detail="Job is halfway done.",
        )

        # Assert that the update method was called with the custom parameters
        mock_update_custom.assert_called_once_with(
            {
                "status": ProcessorStatus.to_json(ProcessorStatus.IN_PROGRESS),
                "progress": 50.0,
                "detail": "Job is halfway done.",
            },
            mocker.ANY,  # We can match the query condition later
        )
        assert mock_query.called_once()


class TestRSPYStagingCatalog:
    """Group of all tests used for method that search the catalog before processing."""

    @pytest.mark.asyncio
    async def test_check_catalog_succes(self, mocker, staging_instance):
        """Test the check_catalog method for successful execution.

        This test verifies that the check_catalog method correctly formats the request
        to the catalog URL and handles the response appropriately.

        Args:
            mocker: The mocker fixture to patch methods and objects during tests.
            staging_instance (RSPYStaging): An instance of the RSPYStaging class, pre-initialized for testing.
        """
        # Mocking the item_collection and its features
        staging_instance.item_collection = mocker.Mock()
        staging_instance.item_collection.features = [mocker.Mock(id="1"), mocker.Mock(id="2")]

        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"
        staging_instance.headers = {"cookie": "test_cookie"}

        # mock all other called methods
        mock_create_streaming_list = mocker.patch.object(staging_instance, "create_streaming_list", return_value=None)
        mock_log_job_execution = mocker.patch.object(staging_instance, "log_job_execution", return_value=None)

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"type": "FeatureCollection", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mocker.patch("requests.get", return_value=mock_response)

        # Call the method under test
        result = await staging_instance.check_catalog()

        # Assert that the result is True (successful catalog check)
        assert result is True

        # Construct the expected filter string
        expected_filter_string = "id IN ('1', '2')"
        expected_filter_object = {"filter-lang": "cql2-text", "filter": expected_filter_string, "limit": 2}
        collection = "test_collection"
        # Assert that requests.get was called with the correct parameters
        requests.get.assert_called_once_with(  # type: ignore
            f"{staging_instance.catalog_url}/catalog/collections/{collection}/search",
            headers={"cookie": "test_cookie"},
            params=expected_filter_object,
            timeout=5,
        )
        mock_create_streaming_list.called_once()
        mock_log_job_execution.called_once()

    @pytest.mark.asyncio
    async def test_check_catalog_failure(self, mocker, staging_instance):
        """Test the check_catalog method for successful execution.

        This test verifies that the check_catalog method correctly formats the request
        to the catalog URL and handles the response appropriately.

        Args:
            mocker: The mocker fixture to patch methods and objects during tests.
            staging_instance (RSPYStaging): An instance of the RSPYStaging class, pre-initialized for testing.
        """
        # Mocking the item_collection and its features
        staging_instance.item_collection = mocker.Mock()
        staging_instance.item_collection.features = [mocker.Mock(id=1), mocker.Mock(id=2)]

        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"
        staging_instance.headers = {"cookie": "test_cookie"}

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
            result = await staging_instance.check_catalog()

            # Assert that the result is False (failed catalog check)
            assert result is False

            # Assert that create_streaming_list was not called during failure
            mock_create_streaming_list.assert_not_called()
            mock_log_job_execution.assert_called_once_with(
                ProcessorStatus.FAILED,
                0,
                detail=f"Failed to search catalog: {get_err_msg}",
            )

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"type": "FeatureCollection", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mock_log_job_execution = mocker.patch.object(staging_instance, "log_job_execution", return_value=None)
        mocker.patch("requests.get", return_value=mock_response)
        err_msg = "RE test msg"
        mock_create_streaming_list = mocker.patch.object(
            staging_instance,
            "create_streaming_list",
            side_effect=RuntimeError(err_msg),
        )
        # Call the method under test
        result = await staging_instance.check_catalog()
        mock_log_job_execution.assert_called_once_with(
            ProcessorStatus.FAILED,
            0,
            detail=f"Failed to search catalog: {err_msg}",
        )


class TestRSPYPrepareStreaming:
    """Class that groups tests for methods that prepare inputs for streaming process."""

    def test_create_streaming_list_all_downloaded(self, mocker, staging_instance):
        """Test create_streaming_list when all features are already downloaded."""
        # Set up the staging instance
        staging_instance.item_collection.features = [mocker.Mock(id=1), mocker.Mock(id=2)]

        # Create a mock catalog response indicating all features have been downloaded
        catalog_response = {"context": {"returned": 2}, "features": [{"id": 1}, {"id": 2}]}

        # Call the method under test
        staging_instance.create_streaming_list(catalog_response)

        # Assert that stream_list is empty
        assert staging_instance.stream_list == []

    def test_create_streaming_list_no_download(self, mocker, staging_instance):
        """Test create_streaming_list when no features are found in the catalog."""
        staging_instance.item_collection.features = [mocker.Mock(id=1), mocker.Mock(id=2)]

        # Create a mock catalog response with no features found
        catalog_response = {"context": {"returned": 0}, "features": []}

        staging_instance.create_streaming_list(catalog_response)

        # Assert that stream_list contains all features
        assert staging_instance.stream_list == staging_instance.item_collection.features

    def test_create_streaming_list_partial_download(self, mocker, staging_instance):
        """Test create_streaming_list when some features are not yet downloaded."""
        feature_1 = mocker.Mock(id=1)
        feature_2 = mocker.Mock(id=2)
        feature_3 = mocker.Mock(id=3)
        staging_instance.item_collection.features = [feature_1, feature_2, feature_3]

        # Create a mock catalog response indicating only some features have been downloaded
        catalog_response = {"context": {"returned": 1}, "features": [{"id": 1}]}  # Only feature 1 has been downloaded

        staging_instance.create_streaming_list(catalog_response)

        # Assert that stream_list contains features 2 and 3 (not downloaded)
        assert staging_instance.stream_list == [feature_2, feature_3]

    def test_prepare_streaming_tasks_all_valid(self, mocker, staging_instance):
        """Test prepare_streaming_tasks when all assets are valid."""
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {
            "asset1": mocker.Mock(href="https://example.com/asset1", title="asset1_title"),
            "asset2": mocker.Mock(href="https://example.com/asset2", title="asset2_title"),
        }

        result = staging_instance.prepare_streaming_tasks(feature)

        # Assert that the method returns True
        assert result is True
        # Assert that assets_info has been populated correctly
        assert staging_instance.assets_info == [
            ("https://example.com/asset1", f"{staging_instance.catalog_collection}/{feature.id}/asset1_title"),
            ("https://example.com/asset2", f"{staging_instance.catalog_collection}/{feature.id}/asset2_title"),
        ]
        # Assert that asset hrefs are updated correctly
        assert (
            feature.assets["asset1"].href
            == f"s3://rtmpop/{staging_instance.catalog_collection}/{feature.id}/\
asset1_title"
        )
        assert (
            feature.assets["asset2"].href
            == f"s3://rtmpop/{staging_instance.catalog_collection}/{feature.id}/\
asset2_title"
        )


class TestRSPYStagingTaskFailure:  # pylint: disable=too-few-public-methods
    """Class to group tests that handle dask task failure"""

    def test_handle_task_failure_all_tasks_canceled(self, mocker, staging_instance):
        """Test handle_task_failure when all tasks are successfully canceled."""
        # Create mock tasks
        task_1 = mocker.Mock()
        task_1.done.return_value = False
        task_1.key = "task_1_key"
        task_1.status = "pending"

        task_2 = mocker.Mock()
        task_2.done.return_value = False
        task_2.key = "task_2_key"
        task_2.status = "pending"

        staging_instance.tasks = [task_1, task_2]

        # Call the handle_task_failure method with a sample exception
        error = Exception()
        staging_instance.handle_task_failure(error)

        # both tasks were canceled
        task_1.cancel.assert_called_once()
        task_2.cancel.assert_called_once()


class TestRSPYStagingDeleteFromBucket:
    """Class used to group tests that handle file bucket removal if failure"""

    def test_delete_files_from_bucket_succes(self, mocker, staging_instance):
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

    def test_delete_files_from_bucket_empty(self, mocker, staging_instance):
        """Test delete files with no assets, nothing should happen."""
        staging_instance.assets_info = []
        # Mock S3StorageHandler to ensure it's not used
        mock_s3_handler = mocker.Mock()
        mocker.patch("rs_server_staging.processors.S3StorageHandler", return_value=mock_s3_handler)
        # Call the method
        staging_instance.delete_files_from_bucket()
        # Assert that delete_file_from_s3 was never called since there are no assets
        mock_s3_handler.delete_file_from_s3.assert_not_called()

    def test_delete_files_from_bucket_failed_to_create_s3_handler(self, mocker, staging_instance):
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

    def test_delete_files_from_bucket_fail_while_in_progress(self, mocker, staging_instance):
        """Test a runtimeerror while using s3_handler.delete_file_from_s3, should produce a logger error,
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


class TestRSPYStagingMainExecution:
    """Class to test Item processing"""

    # def test_dask_cluster_connect(self, mocker, staging_instance):
    #     """Test to mock the connection to a dask cluster"""
    #     # Mock environment variables to simulate gateway mode
    #     mocker.patch.dict(
    #         os.environ,
    #         {
    #             "DASK_GATEWAY__ADDRESS": "gateway-address",
    #             "DASK_GATEWAY__AUTH__TYPE": "jupyterhub",
    #             "JUPYTERHUB_API_TOKEN": "mock_api_token"
    #         },
    #     )
    #     staging_instance.cluster = None
    #     staging_instance.logger = mocker.Mock()
    #     # Mock the JupyterHubAuth, Gateway, and Client classes
    #     mock_auth = mocker.patch('dask_gateway.auth.JupyterHubAuth',
    #                              return_value=JupyterHubAuth(api_token="mock_api_token"))
    #     mock_gateway = mocker.patch('dask_gateway.Gateway')
    #     mock_list_clusters = mocker.patch.object(Gateway, 'list_clusters')
    #     mock_connect = mocker.patch.object(Gateway, 'connect')
    #     mock_client = mocker.patch('rs_server_staging.processors.Client', autospec=True, return_value=None)
    #     # Mock the Security object
    #     mock_security = mocker.patch('dask.distributed.Security')
    #     # Mock the cluster with the required attributes for Client
    #     mock_cluster = mocker.Mock()
    #     mock_cluster.name = "test-cluster"
    #     mock_cluster.dashboard_link = "http://mock-dashboard"
    #     mock_cluster.scheduler_address = "tcp://mock-scheduler-address"  # Set a valid scheduler address
    #     mock_cluster.security = mock_security  # Add mocked security attribute
    #     mock_list_clusters.return_value = [mock_cluster]
    #     mock_connect.return_value = mock_cluster

    #     # Setup client mock
    #     mock_scheduler_info = {"workers": {"worker-1": {}, "worker-2": {}}}
    #     mock_client_instance = mocker.Mock()
    #     mock_client_instance.scheduler_info.return_value = mock_scheduler_info
    #     mock_client.return_value = mock_client_instance

    #     # Call the method under test
    #     client = staging_instance.dask_cluster_connect()

    #     # Assert that the Gateway was instantiated correctly
    #     mock_auth.assert_called_once_with(api_token="mock_api_token")
    #     mock_gateway.assert_called_once_with(
    #         address="gateway-address", auth=mock_auth.return_value
    #     )
    #     mock_list_clusters.assert_called_once()
    #     mock_connect.assert_called_once_with("test-cluster")
    #     mock_client.assert_called_once_with(staging_instance.cluster)

    #     # Ensure logging was called as expected
    #     staging_instance.logger.debug.assert_any_call(f"The list of clusters: {mock_list_clusters.return_value}")
    #     staging_instance.logger.info.assert_any_call("Number of running workers: 2")
    #     staging_instance.logger.debug.assert_any_call(
    # f"Dask Client: {client} | Cluster dashboard: {mock_connect.return_value.dashboard_link}")

    def test_dask_cluster_connect_failure_no_envs(self, mocker, staging_instance):
        """Test to mock the connection to a dask cluster"""
        # Mock environment variables to simulate gateway mode
        mocker.patch.dict(
            os.environ,
            {
                "DASK_GATEWAY__ADDRESS": "gateway-address",
            },
        )
        staging_instance.cluster = None
        with pytest.raises(RuntimeError) as exc_info:
            staging_instance.dask_cluster_connect()
            assert "Could not find the needed environment variable" in str(exc_info.value)

    def test_manage_dask_tasks_results_succesfull(self, mocker, staging_instance):
        """Test to mock managing of successul tasks"""
        # Mock tasks that will succeed
        task1 = mocker.Mock()
        task1.result = mocker.Mock(return_value=None)  # Simulate a successful task
        task1.key = "task1"

        task2 = mocker.Mock()
        task2.result = mocker.Mock(return_value=None)  # Simulate another successful task
        task2.key = "task2"
        # mock dask client
        client = mocker.Mock(return_value=True)
        staging_instance.tasks = [task1, task2]  # Set tasks
        staging_instance.stream_list = [task1, task2]  # set streaming list
        # mock distributed as_completed
        mocker.patch("rs_server_staging.processors.as_completed", return_value=[task1, task2])
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mock_publish_feature = mocker.patch.object(staging_instance, "publish_rspy_feature")

        staging_instance.manage_dask_tasks_results(client)

        # mock_log_job.assert_any_call(ProcessorStatus.IN_PROGRESS, None, detail='In progress')
        # Check that status was updated 3 times during execution, 1 time for each task, and 1 time with FINISH
        mock_log_job.assert_any_call(ProcessorStatus.FINISHED, 100, detail="Finished")
        assert mock_log_job.call_count == 3
        # Check that feature publish method was called.
        mock_publish_feature.assert_called()

    def test_manage_dask_tasks_results_failure(self, mocker, staging_instance):
        """Test handling callbacks when error on one task"""
        task1 = mocker.Mock()
        task1.result = mocker.Mock(return_value=None, side_effect=Exception)  # Simulate a exception in task
        task1.key = "task1"
        client = mocker.Mock(return_value=True)
        staging_instance.tasks = [task1]
        # Create mock for task, and distributed.as_completed func
        mocker.patch("rs_server_staging.processors.as_completed", return_value=[task1])
        # Create mock for handle_task_failure, publish_rspy_feature, delete_files_from_bucket, log_job_execution methods
        mock_task_failure = mocker.patch.object(staging_instance, "handle_task_failure")
        mock_publish_feature = mocker.patch.object(staging_instance, "publish_rspy_feature")
        mock_delete_file_from_bucket = mocker.patch.object(staging_instance, "delete_files_from_bucket")
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        # Set timeout to 0, in order to skip that while loop
        mocker.patch.dict("os.environ", {"RSPY_STAGING_TIMEOUT": "0"})

        staging_instance.manage_dask_tasks_results(client)

        mock_task_failure.assert_called()  # handle_task_failure called once
        mock_delete_file_from_bucket.assert_called()  # Bucket removal called once
        # logger set status to failed
        mock_log_job.assert_called_once_with(ProcessorStatus.FAILED, None, detail="At least one of the tasks failed: ")
        # Features are not published here.
        mock_publish_feature.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_rspy_features_empty_stream(self, mocker, staging_instance):
        """Test that process_rspy_features logs the initial setup and starts the main loop."""

        # Mock dependencies
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=True)

        # Set the stream_list to an empty list (no features to process)
        staging_instance.stream_list = []

        # Call the method
        await staging_instance.process_rspy_features()

        # Assert initial logging and job execution calls
        mock_log_job.assert_any_call(ProcessorStatus.IN_PROGRESS, 0, detail="Sending tasks to the dask cluster")
        mock_log_job.assert_called_with(ProcessorStatus.FINISHED, 100, detail="Finished without processing any tasks")

    @pytest.mark.asyncio
    async def test_process_rspy_features_empty_assets(self, mocker, staging_instance):
        """Test that process_rspy_features handles task preparation failure."""

        # Mock dependencies
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=False)

        # Set stream_list with one feature (to trigger task preparation)
        mock_feature = mocker.Mock()
        staging_instance.stream_list = [mock_feature]

        # Call the method
        await staging_instance.process_rspy_features()

        # Ensure the task preparation failed, and method returned early
        mock_log_job.assert_any_call(ProcessorStatus.IN_PROGRESS, 0, detail="Sending tasks to the dask cluster")
        mock_log_job.assert_called_with(ProcessorStatus.FAILED, 0, detail="Unable to create tasks for the Dask cluster")


class TestRSPYStagingPublishCatalog:
    """Class to group tests for catalog publishing after streaming was processes"""

    def test_publish_rspy_feature_success(self, mocker, staging_instance):
        """Test successful feature publishing to the catalog."""
        feature = mocker.Mock()  # Mock the feature object
        feature.json.return_value = '{"id": "feature1", "properties": {"name": "test"}}'  # Mock the JSON serialization

        # Mock requests.post to return a successful response
        mock_response = mocker.Mock()
        mock_response.raise_for_status.return_value = None  # No error
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        result = staging_instance.publish_rspy_feature(feature)

        assert result is True  # Should return True for successful publishing
        mock_post.assert_called_once_with(
            f"{staging_instance.catalog_url}/catalog/collections/{staging_instance.catalog_collection}/items",
            headers={"cookie": staging_instance.headers.get("cookie", None)},
            data=feature.json(),
            timeout=10,
        )
        feature.json.assert_called()  # Ensure the feature JSON serialization was called

    def test_publish_rspy_feature_fail(self, mocker, staging_instance):
        """Test failure during feature publishing and cleanup on error."""
        feature = mocker.Mock()
        feature.json.return_value = '{"id": "feature1", "properties": {"name": "test"}}'

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

            result = staging_instance.publish_rspy_feature(feature)

            assert result is False  # Should return False for failure
            mock_post.assert_called_once_with(
                f"{staging_instance.catalog_url}/catalog/collections/{staging_instance.catalog_collection}/items",
                headers={"cookie": staging_instance.headers.get("cookie", None)},
                data=feature.json(),
                timeout=10,
            )
            mock_logger.error.assert_called_once_with("Error while publishing items to rspy catalog %s", mocker.ANY)

    def test_repr(self, staging_instance):
        """Test repr method for coverage"""
        assert repr(staging_instance) == "RSPY Staging OGC API Processor"


# Disabled for moment
# class TestRSPYStagingDaskSerialization:
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
