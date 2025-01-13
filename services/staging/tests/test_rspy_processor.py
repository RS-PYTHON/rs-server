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

"""Test module for Staging processor."""
import asyncio
import os
from concurrent.futures import CancelledError
from datetime import datetime
from typing import Dict
from unittest.mock import call

import pytest
import requests
from dask_gateway import Gateway
from fastapi import HTTPException
from rs_server_staging.processors import TokenAuth, streaming_task
from rs_server_staging.staging_job_status import EStagingStatus

# pylint: disable=undefined-variable
# pylint: disable=no-member
# pylint: disable=too-many-lines


class TestProcessorStatus:  # pylint: disable=too-few-public-methods
    """Class for tests of EStagingStatus enum"""

    def test_str_method(self):
        """Test the __str__ method of EStagingStatus."""
        assert str(EStagingStatus.QUEUED) == "queued"
        assert str(EStagingStatus.FINISHED) == "finished"
        assert str(EStagingStatus.FAILED) == "failed"
        assert str(EStagingStatus.CREATED) == "created"
        assert str(EStagingStatus.STARTED) == "started"
        assert str(EStagingStatus.IN_PROGRESS) == "in_progress"
        assert str(EStagingStatus.STOPPED) == "stopped"
        assert str(EStagingStatus.PAUSED) == "paused"
        assert str(EStagingStatus.RESUMED) == "resumed"
        assert str(EStagingStatus.CANCELLED) == "cancelled"


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

    def test_streaming_task(self, mocker):
        """Test a error while creating s3 handler"""
        # mock init of s3 handler without S3_ACCESSKEY, should raise an error while creating s3 handler
        # Mock S3StorageHandler and its delete_file_from_s3 method
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "fake_endpoint",
                "S3_REGION": "fake_region",
            },
        )
        mock_s3_handler = mocker.Mock()
        mocker.patch("rs_server_staging.processors.S3StorageHandler", return_value=mock_s3_handler)

        s3_key = "s3_path/file.zip"
        mocker.patch(
            "rs_server_staging.processors.S3StorageHandler.s3_streaming_upload",
            return_value=None,
        )

        assert streaming_task("https://example.com/product.zip", [], "Bearer token", "bucket", s3_key) == s3_key

    def test_streaming_task_incorrect_env(self, mocker):
        """Test a error while creating s3 handler"""
        # mock init of s3 handler without S3_ACCESSKEY, should raise an error while creating s3 handler
        mocker.patch.dict(
            "os.environ",
            {"S3_SECRETKEY": "fake_secret_key", "S3_ENDPOINT": "fake_endpoint", "S3_REGION": "fake_region"},
        )
        with pytest.raises(ValueError, match=r"Cannot create s3 connector object."):
            streaming_task("https://example.com/product.zip", [], "Bearer token", "bucket", "file.zip")

    def test_streaming_task_runtime_error(self, mocker):
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
            match=r"Dask task failed to stream file from https://example.com/product.zip to s3://bucket/file.zip",
        ):
            streaming_task("https://example.com/product.zip", [], "Bearer token", "bucket", "file.zip")


class TestStaging:
    """Test class for Staging processor"""

    @pytest.mark.asyncio
    async def test_execute_with_running_loop(self, mocker, staging_instance, asyncio_loop):
        """Test execute method while a asyncio loop is running"""
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mock_check_catalog = mocker.patch.object(staging_instance, "check_catalog", return_value=True)
        mock_process_rspy = mocker.patch.object(staging_instance, "process_rspy_features", return_value=True)
        # Mocking the item_collection and its features
        staging_instance.item_collection = mocker.Mock()
        staging_instance.item_collection.features = [mocker.Mock(id="1"), mocker.Mock(id="2")]
        # Simulate an already running event loop
        mocker.patch.object(asyncio, "get_event_loop", return_value=asyncio_loop)
        mocker.patch.object(asyncio_loop, "is_running", return_value=True)

        # Call the async execute method
        result = await staging_instance.execute()

        # Assertions
        assert mock_log_job.call_count == 2
        mock_log_job.assert_has_calls(
            [call(EStagingStatus.CREATED), call(EStagingStatus.STARTED, 0, detail="Successfully searched catalog")],
        )
        mock_check_catalog.assert_called_once()
        mock_process_rspy.assert_called_once()  # Ensures processing is scheduled
        assert result == {"started": staging_instance.job_id}

    @pytest.mark.asyncio
    async def test_execute_fails_in_checking_catalog(self, mocker, staging_instance, asyncio_loop):
        """Test execute method while a asyncio loop is running"""
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        mock_check_catalog = mocker.patch.object(staging_instance, "check_catalog", return_value=False)
        # Mocking the item_collection and its features
        staging_instance.item_collection = mocker.Mock()
        staging_instance.item_collection.features = [mocker.Mock(id="1"), mocker.Mock(id="2")]
        # Simulate an already running event loop
        mocker.patch.object(asyncio, "get_event_loop", return_value=asyncio_loop)
        mocker.patch.object(asyncio_loop, "is_running", return_value=True)

        # Call the async execute method
        result = await staging_instance.execute()

        # Assertions
        assert mock_log_job.call_count == 2
        mock_log_job.assert_has_calls(
            [
                call(EStagingStatus.CREATED),
                call(
                    EStagingStatus.FAILED,
                    0,
                    detail="Failed to start the staging process. "
                    f"Checking the collection '{staging_instance.catalog_collection}' failed !",
                ),
            ],
        )
        mock_check_catalog.assert_called_once()

        assert result == {"failed": staging_instance.job_id}

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
            EStagingStatus.FINISHED,
            0,
            detail="No valid items were provided in the input for staging",
        )
        assert result == {"finished": staging_instance.job_id}

    def test_create_job_execution(self, staging_instance, mocker):
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
        staging_instance.status = EStagingStatus.QUEUED
        staging_instance.progress = 0
        staging_instance.detail = "Job is starting."

        # Call the method to test if self attrs are written into db
        staging_instance.create_job_execution()

        # Assert that the insert method was called once with the expected arguments
        mock_db_process_manager.add_job.assert_called_once_with(
            {
                "identifier": "12345",
                "status": EStagingStatus.QUEUED.value.upper(),
                "progress": 0,
                "detail": "Job is starting.",
            },
        )

    def test_log_job_execution(self, staging_instance, mocker):
        """Test the log_job_execution method of the Staging class.

        This test verifies that the log_job_execution method correctly updates the job's status,
        progress, and detail in the db_process_manager database, both for default and custom attributes.

        Args:
            staging_instance (Staging): An instance of the Staging class, pre-initialized for testing.
            mocker (pytest_mock.MockerFixture): The mocker fixture to patch methods and objects during tests.

        """
        # Mock self.db_process_manager and self.lock attrs
        mock_db_process_manager = mocker.Mock()

        staging_instance.db_process_manager = mock_db_process_manager
        staging_instance.job_id = "12345"
        staging_instance.status = EStagingStatus.QUEUED
        staging_instance.progress = 0
        staging_instance.detail = "Job is starting."

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
                "status": EStagingStatus.QUEUED.value.upper(),
                "progress": 0,
                "detail": "Job is starting.",
                "updated_at": fake_now,
            },
        )

        # reset the mock called counter
        mock_update_job.reset_mock()

        # Call log_job_execution to test status update with custom attrs
        staging_instance.log_job_execution(
            status=EStagingStatus.IN_PROGRESS,
            progress=50.0,
            detail="Job is halfway done.",
        )

        # Assert that the update method was called with the custom parameters
        mock_update_job.assert_called_once_with(
            staging_instance.job_id,
            {
                "status": EStagingStatus.IN_PROGRESS.value.upper(),
                "progress": 50.0,
                "detail": "Job is halfway done.",
                "updated_at": fake_now,
            },
        )


class TestStagingCatalog:
    """Group of all tests used for method that search the catalog before processing."""

    @pytest.mark.asyncio
    async def test_check_catalog_success(self, mocker, staging_instance):
        """Test the check_catalog method for successful execution.

        This test verifies that the check_catalog method correctly formats the request
        to the catalog URL and handles the response appropriately.

        Args:
            mocker: The mocker fixture to patch methods and objects during tests.
            staging_instance (Staging): An instance of the Staging class, pre-initialized for testing.
        """
        # Mocking the item_collection and its features
        staging_instance.item_collection = mocker.Mock()
        staging_instance.item_collection.features = [mocker.Mock(id="1"), mocker.Mock(id="2")]

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
        result = await staging_instance.check_catalog()

        # Assert that the result is True (successful catalog check)
        assert result is True

        # Construct the expected filter string
        expected_filter_string = "id IN ('1', '2')"
        expected_filter_object = {"filter-lang": "cql2-text", "filter": expected_filter_string, "limit": "2"}
        collection = "test_collection"
        # Assert that requests.get was called with the correct parameters
        requests.get.assert_called_once_with(  # type: ignore
            f"{staging_instance.catalog_url}/catalog/collections/{collection}/search",
            headers={"cookie": "fake-cookie"},
            params=expected_filter_object,
            timeout=5,
        )
        mock_create_streaming_list.called_once()
        mock_log_job_execution.called_once()

    @pytest.mark.asyncio
    async def test_check_catalog_get_wrong_response(self, mocker, staging_instance):
        """docstring to be added"""
        # Mocking the item_collection and its features
        staging_instance.item_collection = mocker.Mock()
        staging_instance.item_collection.features = [mocker.Mock(id="1"), mocker.Mock(id="2")]

        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"wrong_key": "Unknown_test", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mocker.patch("requests.get", return_value=mock_response)

        # Call the method under test
        result = await staging_instance.check_catalog()

        # Assert that the result is True (successful catalog check)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_catalog_failure(self, mocker, staging_instance):
        """docstring to be added"""
        # Mocking the item_collection and its features
        staging_instance.item_collection = mocker.Mock()
        staging_instance.item_collection.features = [mocker.Mock(id=1), mocker.Mock(id=2)]

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
            result = await staging_instance.check_catalog()

            # Assert that the result is False (failed catalog check)
            assert result is False

            # Assert that create_streaming_list was not called during failure
            mock_create_streaming_list.assert_not_called()
            mock_log_job_execution.assert_called_once_with(
                EStagingStatus.FAILED,
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
        mocker.patch.object(
            staging_instance,
            "create_streaming_list",
            side_effect=RuntimeError(err_msg),
        )
        # Call the method under test
        await staging_instance.check_catalog()
        mock_log_job_execution.assert_called_once_with(
            EStagingStatus.FAILED,
            0,
            detail=f"Failed to search catalog: {err_msg}",
        )


class TestPrepareStreaming:
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
        # Only feature 1 has been already staged
        catalog_response = {"context": {"returned": 1}, "features": [{"id": 1}]}

        staging_instance.create_streaming_list(catalog_response)

        # Assert that stream_list contains features 2 and 3 (not downloaded)
        assert staging_instance.stream_list == [feature_2, feature_3]

    def test_create_streaming_list_wrong_catalog_input(self, mocker, staging_instance):
        """Test create_streaming_list when a wrong response is received from the catalog."""
        feature_1 = mocker.Mock(id=1)
        feature_2 = mocker.Mock(id=2)
        feature_3 = mocker.Mock(id=3)
        staging_instance.item_collection.features = [feature_1, feature_2, feature_3]

        # Create a mock catalog response which is malformed
        catalog_response = {"context": {"returned": 1}, "wrong_key": [{"id": 1}]}

        with pytest.raises(
            RuntimeError,
            match="The 'features' field is missing in the response from the catalog service. ",
        ):
            staging_instance.create_streaming_list(catalog_response)

    def test_prepare_streaming_tasks_all_valid(self, mocker, staging_instance):
        """Test prepare_streaming_tasks when all assets are valid."""
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {
            "asset1": mocker.Mock(href="https://example.com/asset1"),
            "asset2": mocker.Mock(href="https://example.com/asset2"),
        }

        result = staging_instance.prepare_streaming_tasks(feature)

        # Assert that the method returns True
        assert result is True
        # Assert that assets_info has been populated correctly
        assert staging_instance.assets_info == [
            ("https://example.com/asset1", f"{staging_instance.catalog_collection}/{feature.id}/asset1"),
            ("https://example.com/asset2", f"{staging_instance.catalog_collection}/{feature.id}/asset2"),
        ]
        # Assert that asset hrefs are updated correctly
        assert (
            feature.assets["asset1"].href
            == f"s3://rtmpop/{staging_instance.catalog_collection}/{feature.id}/\
asset1"
        )
        assert (
            feature.assets["asset2"].href
            == f"s3://rtmpop/{staging_instance.catalog_collection}/{feature.id}/\
asset2"
        )

    def test_prepare_streaming_tasks_one_invalid(self, mocker, staging_instance):
        """Test prepare_streaming_tasks when all assets are valid."""
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {
            "asset1": mocker.Mock(href="", title="asset1_title"),
            "asset2": mocker.Mock(href="https://example.com/asset2", title="asset2_title"),
        }
        result = staging_instance.prepare_streaming_tasks(feature)

        # Assert that the method returns False
        assert result is False


class TestStagingTaskFailure:  # pylint: disable=too-few-public-methods
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

    def test_handle_task_failure_with_canceled_error(self, mocker, staging_instance):
        """Test handle_task_failure when one task raises CanceledError"""
        # Mock task objects
        mock_task1 = mocker.Mock()
        mock_task1.done.return_value = False  # Simulate an incomplete task
        mock_task1.key = "task1"
        mock_task1.status = "pending"

        mock_task2 = mocker.Mock()
        mock_task2.done.return_value = True  # Simulate a completed task
        mock_task2.key = "task2"
        mock_task2.status = "finished"

        # Mock the CancelledError
        mock_cancelled_error = CancelledError("Task already cancelled")

        # Create a sample object with attributes
        staging_instance.tasks = [mock_task1, mock_task2]
        mock_logger = mocker.patch.object(staging_instance, "logger")

        # Mock the error passed to the function
        sample_error = Exception("Test error")

        # Call the function under test
        staging_instance.handle_task_failure(sample_error)

        # Assertions for logger calls
        mock_logger.error.assert_any_call(
            "Error during staging. Canceling all the remaining tasks. "
            "The assets already copied to the bucket will be deleted."
            "The error: %s",
            sample_error,
        )

        mock_logger.info.assert_called_once_with("Canceling task %s status %s", "task1", "pending")

        # Ensure task1 is cancelled
        mock_task1.cancel.assert_called_once()

        # Ensure task2 is not cancelled because it's already done
        mock_task2.cancel.assert_not_called()

        # Simulate catching a CancelledError and logging it
        mock_task1.cancel.side_effect = mock_cancelled_error

        # Run the function again to trigger the CancelledError
        staging_instance.handle_task_failure(sample_error)

        # Ensure that the CancelledError is logged
        mock_logger.error.assert_any_call("Task was already cancelled: %s", mock_cancelled_error)


class TestStagingDeleteFromBucket:
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

    def test_dask_cluster_connect(self, mocker, staging_instance, cluster_options):
        """Test to mock the connection to a dask cluster"""
        # Mock environment variables to simulate gateway mode
        mocker.patch.dict(
            os.environ,
            {
                "DASK_GATEWAY__ADDRESS": "gateway-address",
                "DASK_GATEWAY__AUTH__TYPE": "jupyterhub",
                "JUPYTERHUB_API_TOKEN": "mock_api_token",
                "RSPY_DASK_STAGING_CLUSTER_NAME": cluster_options["cluster_name"],
            },
        )
        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        staging_instance.cluster = None
        # Mock the JupyterHubAuth, Gateway, and Client classes
        mock_list_clusters = mocker.patch.object(Gateway, "list_clusters")
        mock_connect = mocker.patch.object(Gateway, "connect")
        mock_client = mocker.patch("rs_server_staging.processors.Client", autospec=True, return_value=None)
        # Mock the Security object
        mock_security = mocker.patch("dask.distributed.Security")
        # Mock the cluster with the required attributes for Client
        mock_cluster = mocker.Mock()
        mock_cluster.name = "dask-gateway-id"
        mock_cluster.options = cluster_options
        mock_cluster.dashboard_link = "https://mock-dashboard"
        mock_cluster.scheduler_address = "tcp://mock-scheduler-address"  # Set a valid scheduler address
        mock_cluster.security = mock_security  # Add mocked security attribute
        mock_list_clusters.return_value = [mock_cluster]
        mock_connect.return_value = mock_cluster

        # Setup client mock
        mock_scheduler_info: Dict[str, Dict] = {"workers": {"worker-1": {}, "worker-2": {}}}
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
        mock_logger.debug.assert_any_call(f"The list of clusters: {mock_list_clusters.return_value}")
        mock_logger.info.assert_any_call("Number of running workers: 2")
        mock_logger.debug.assert_any_call(
            f"Dask Client: {client} | Cluster dashboard: {mock_connect.return_value.dashboard_link}",
        )

    def test_dask_cluster_connect_failure_no_cluster_name(self, mocker, staging_instance, cluster_options):
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
        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        staging_instance.cluster = None
        # Mock the JupyterHubAuth, Gateway, and Client classes
        mock_list_clusters = mocker.patch.object(Gateway, "list_clusters")
        mock_connect = mocker.patch.object(Gateway, "connect")

        # Mock the Security object
        mock_security = mocker.patch("dask.distributed.Security")
        # Mock the cluster with the required attributes for Client
        mock_cluster = mocker.Mock()
        mock_cluster.name = "dask-gateway-id"
        mock_cluster.options = cluster_options
        mock_cluster.dashboard_link = "https://mock-dashboard"
        mock_cluster.scheduler_address = "tcp://mock-scheduler-address"  # Set a valid scheduler address
        mock_cluster.security = mock_security  # Add mocked security attribute
        mock_list_clusters.return_value = [mock_cluster]
        mock_connect.return_value = mock_cluster

        with pytest.raises(RuntimeError):
            staging_instance.dask_cluster_connect()
        # Ensure logging was called as expected
        mock_logger.exception.assert_any_call(
            "Failed to find the specified dask cluster: " f"No dask cluster named '{non_existent_cluster}' was found.",
        )

    def test_dask_cluster_connect_failure_no_envs(self, mocker, staging_instance):
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

        # mock_log_job.assert_any_call(EStagingStatus.IN_PROGRESS, None, detail='In progress')
        # Check that status was updated 3 times during execution, 1 time for each task, and 1 time with FINISH
        mock_log_job.assert_any_call(EStagingStatus.FINISHED, 100, detail="Finished")
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
        mock_log_job.assert_called_once_with(EStagingStatus.FAILED, None, detail="At least one of the tasks failed: ")
        # Features are not published here.
        mock_publish_feature.assert_not_called()

    def test_manage_dask_tasks_failed_to_publish(self, mocker, staging_instance):
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

        mocker.patch.object(staging_instance, "publish_rspy_feature", return_value=False)
        mock_delete_file_from_bucket = mocker.patch.object(staging_instance, "delete_files_from_bucket")

        staging_instance.manage_dask_tasks_results(client)

        mock_log_job.assert_any_call(
            EStagingStatus.FAILED,
            None,
            detail=f"The item {task1.id} couldn't be " "published in the catalog. Cleaning up",
        )
        mock_delete_file_from_bucket.assert_called()

    def test_manage_dask_tasks_no_dask_client(self, mocker, staging_instance):
        """Test the manage_dask_tasks when no valid dask client is received"""
        mock_logger = mocker.patch.object(staging_instance, "logger")
        staging_instance.manage_dask_tasks_results(None)
        mock_logger.error.assert_called_once_with("The dask cluster client object is not created. Exiting")

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
        mock_log_job.assert_called_with(EStagingStatus.FAILED, 0, detail="Unable to create tasks for the Dask cluster")

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
        mock_log_job.assert_called_with(EStagingStatus.FINISHED, 100, detail="Finished without processing any tasks")

    @pytest.mark.asyncio
    async def test_process_rspy_features_token_failure(self, mocker, staging_instance):
        """Test case where retrieving the token raises an exception."""
        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")

        # Simulate successful task preparation
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=True)
        mock_dask_cluster_connect = mocker.patch.object(staging_instance, "dask_cluster_connect")
        staging_instance.assets_info = ["some_asset"]

        # Simulate an exception in the token retrieval
        mocker.patch(
            "rs_server_staging.processors.load_external_auth_config_by_station_service",
            return_value=mocker.Mock(),
        )
        mocker.patch(
            "rs_server_staging.processors.get_station_token",
            side_effect=HTTPException(status_code=404, detail="Token error"),
        )

        # Call the async function
        await staging_instance.process_rspy_features()

        # Verify logger and log_job_execution are called with the error details
        mock_logger.error.assert_called_once_with(
            "Failed to retrieve the token needed to connect to the external station: 404: Token error",
        )
        mock_log_job.assert_called_once_with(
            EStagingStatus.FAILED,
            0,
            detail="Failed to retrieve the token needed to connect to the external station cadip",
        )

        # Verify the function returns early without proceeding to Dask cluster connection
        mock_dask_cluster_connect.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_rspy_features_dask_connection_failure(self, mocker, staging_instance):
        """Test case where connecting to the Dask cluster raises a RuntimeError."""
        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        mock_log_job = mocker.patch.object(staging_instance, "log_job_execution")
        # Simulate successful task preparation
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=True)
        staging_instance.assets_info = ["some_asset"]

        # Mock the called methods
        mock_submit_tasks = mocker.patch.object(staging_instance, "submit_tasks_to_dask_cluster")
        mock_manage_dask_tasks = mocker.patch.object(staging_instance, "manage_dask_tasks_results")
        # Mock token retrieval
        mocker.patch(
            "rs_server_staging.processors.load_external_auth_config_by_station_service",
            return_value=mocker.Mock(),
        )
        mocker.patch("rs_server_staging.processors.get_station_token", return_value="mock_token")

        # Simulate a RuntimeError during Dask cluster connection
        mocker.patch.object(
            staging_instance,
            "dask_cluster_connect",
            side_effect=RuntimeError("Dask cluster client failed"),
        )

        # Call the async function
        await staging_instance.process_rspy_features()

        # Verify log_job_execution is called with the error details
        mock_log_job.assert_called_once_with(EStagingStatus.FAILED, 0, detail="Dask cluster client failed")
        mock_logger.error.assert_called_once_with("Failed to start the staging process")

        # Verify that the task submission and monitoring thread are not executed
        mock_submit_tasks.assert_not_called()
        mock_manage_dask_tasks.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_rspy_features_success(self, mocker, staging_instance):
        """Test case where the entire process runs successfully."""

        # Mock the logger
        mock_logger = mocker.patch.object(staging_instance, "logger")
        mocker.patch.object(staging_instance, "log_job_execution")
        # Simulate successful task preparation
        mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=True)
        staging_instance.assets_info = ["some_asset"]

        # Mock the called methods
        mock_submit_tasks = mocker.patch.object(staging_instance, "submit_tasks_to_dask_cluster")
        mock_manage_dask_tasks = mocker.patch.object(staging_instance, "manage_dask_tasks_results")
        # Mock token retrieval
        mocker.patch(
            "rs_server_staging.processors.load_external_auth_config_by_station_service",
            return_value=mocker.Mock(),
        )

        mocker.patch(
            "rs_server_staging.processors.load_external_auth_config_by_station_service",
            return_value="mock_external_auth_config",
        )
        # Mock the external auth configuration
        mock_external_auth_config = mocker.Mock()
        mock_external_auth_config.trusted_domains = ["test_trusted.example"]  # Set the trusted_domains member
        mocker.patch(
            "rs_server_staging.processors.load_external_auth_config_by_station_service",
            return_value=mock_external_auth_config,
        )
        mocker.patch("rs_server_staging.processors.get_station_token", return_value="mock_token")

        # Mock Dask cluster client
        mock_dask_client = mocker.Mock()
        mocker.patch.object(staging_instance, "dask_cluster_connect", return_value=mock_dask_client)

        # Call the async function
        await staging_instance.process_rspy_features()

        # Verify the function proceeds to Dask task submission
        mock_submit_tasks.assert_called_once_with(
            "mock_token",
            mock_external_auth_config.trusted_domains,
            mock_dask_client,
        )

        # Verify the task monitoring thread is started
        mock_logger.debug.assert_any_call("Starting tasks monitoring thread")
        mock_manage_dask_tasks.assert_called_once_with(mock_dask_client)

        # Ensure the Dask client is closed after the tasks are processed
        mock_dask_client.close.assert_called_once()

        # Verify assets_info is cleared after processing
        assert staging_instance.assets_info == []


class TestStagingPublishCatalog:
    """Class to group tests for catalog publishing after streaming was processes"""

    def test_publish_rspy_feature_success(self, mocker, staging_instance):
        """Test successful feature publishing to the catalog."""
        feature = mocker.Mock()  # Mock the feature object
        feature.json.return_value = '{"id": "feature1", "properties": {"name": "test"}}'  # Mock the JSON serialization
        feature.assets = {}

        # Mock requests.post to return a successful response
        mock_response = mocker.Mock()
        mock_response.raise_for_status.return_value = None  # No error
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        result = staging_instance.publish_rspy_feature(feature)

        assert result is True  # Should return True for successful publishing
        mock_post.assert_called_once_with(
            f"{staging_instance.catalog_url}/catalog/collections/{staging_instance.catalog_collection}/items",
            headers={"cookie": "fake-cookie"},
            data=feature.json(),
            timeout=10,
        )
        feature.json.assert_called()  # Ensure the feature JSON serialization was called

    def test_publish_rspy_feature_fail(self, mocker, staging_instance):
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

            result = staging_instance.publish_rspy_feature(feature)

            assert result is False  # Should return False for failure
            mock_post.assert_called_once_with(
                f"{staging_instance.catalog_url}/catalog/collections/{staging_instance.catalog_collection}/items",
                headers={"cookie": "fake-cookie"},
                data=feature.json(),
                timeout=10,
            )
            mock_logger.error.assert_called_once_with("Error while publishing items to rspy catalog %s", mocker.ANY)

    def test_repr(self, staging_instance):
        """Test repr method for coverage"""
        assert repr(staging_instance) == "RSPY Staging OGC API Processor"


class TestStagingUnpublishCatalog:
    """Class to group tests for catalog unpublishing after streaming failed"""

    def test_unpublish_rspy_features_success(self, mocker, staging_instance):
        """Test successful unpublishing feature ids to the catalog."""
        feature_ids = ["feature-1", "feature-2"]
        mock_logger = mocker.patch.object(staging_instance, "logger")

        # Mock requests.delete to return a successful response

        mock_delete = mocker.patch("requests.delete")
        mock_delete.return_value.status_code = 200

        staging_instance.unpublish_rspy_features(feature_ids)

        # Assert that delete was called with the correct URL and headers
        mock_delete.assert_any_call(
            f"{staging_instance.catalog_url}/catalog/collections/{staging_instance.catalog_collection}/items/feature-1",
            headers={"cookie": "fake-cookie"},
            timeout=3,
        )
        mock_delete.assert_any_call(
            f"{staging_instance.catalog_url}/catalog/collections/{staging_instance.catalog_collection}/items/feature-2",
            headers={"cookie": "fake-cookie"},
            timeout=3,
        )
        # Ensure no error was logged
        mock_logger.error.assert_not_called()

    def test_unpublish_rspy_features_fail(self, mocker, staging_instance):
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

            staging_instance.unpublish_rspy_features(feature_ids)

            mock_delete.assert_any_call(
                f"{staging_instance.catalog_url}/catalog/collections/{staging_instance.catalog_collection}/\
items/feature-1",
                headers={"cookie": "fake-cookie"},
                timeout=3,
            )
            mock_logger.error.assert_called_once_with("Error while deleting the item from rspy catalog %s", mocker.ANY)

    def test_repr(self, staging_instance):
        """Test repr method for coverage"""
        assert repr(staging_instance) == "RSPY Staging OGC API Processor"


class TestStagingSubmitToDaskCluster:
    """Class to group tests for submiting tasks to dask cluster"""

    def test_submit_tasks_to_dask_cluster_success(self, mocker, staging_instance):
        """Test the submiting tasks to dask cluster function when successful"""
        # Mock the Dask client
        mock_client = mocker.Mock()

        # Mock the streaming_task function
        mock_streaming_task = mocker.Mock()

        # Patch the TokenAuth to return a mock object
        mock_token_auth = mocker.patch("rs_server_staging.processors.TokenAuth")

        # Mock assets_info (list of tuples)
        mock_assets_info = [("asset1", "path1"), ("asset2", "path2")]

        # Create a sample object with attributes

        staging_instance.assets_info = mock_assets_info
        staging_instance.catalog_bucket = "mock_bucket"

        # Patch the streaming_task function within the object under test
        mocker.patch("rs_server_staging.processors.streaming_task", mock_streaming_task)

        # Call the function under test
        staging_instance.submit_tasks_to_dask_cluster("mock_token", [], mock_client)

        # Assert that tasks are submitted to the Dask client for each asset
        assert len(staging_instance.tasks) == 2  # Two tasks should be submitted

        # Ensure that client.submit was called with correct arguments
        mock_client.submit.assert_any_call(
            mock_streaming_task,
            "asset1",
            [],
            mock_token_auth.return_value,
            "mock_bucket",
            "path1",
        )
        mock_client.submit.assert_any_call(
            mock_streaming_task,
            "asset2",
            [],
            mock_token_auth.return_value,
            "mock_bucket",
            "path2",
        )

        # Ensure tasks were added to obj.tasks
        assert len(staging_instance.tasks) == 2

    def test_submit_tasks_to_dask_cluster_failure(self, mocker, staging_instance):
        """Test the submiting tasks to dask cluster function when fails"""
        # Mock the Dask client
        mock_client = mocker.Mock()

        # Mock the streaming_task function
        mock_streaming_task = mocker.Mock()

        # Mock assets_info (list of tuples)
        mock_assets_info = [("asset1", "path1")]

        # Create a sample object with attributes
        staging_instance.assets_info = mock_assets_info
        staging_instance.catalog_bucket = "mock_bucket"
        mock_logger = mocker.patch.object(staging_instance, "logger")

        # Patch the streaming_task function within the object under test
        mocker.patch("rs_server_staging.processors.streaming_task", mock_streaming_task)

        # Simulate client.submit raising an exception
        mock_client.submit.side_effect = Exception("Mock submission failure")

        # Call the function under test and catch the RuntimeError
        with pytest.raises(
            RuntimeError,
            match="Submitting task to dask cluster failed. Reason: Mock submission failure",
        ):
            staging_instance.submit_tasks_to_dask_cluster("mock_token", [], mock_client)

        # Ensure the logger catches the exception
        mock_logger.exception.assert_called_once_with(
            "Submitting task to dask cluster failed. Reason: Mock submission failure",
        )

        # Ensure no tasks were added
        assert len(staging_instance.tasks) == 0


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
