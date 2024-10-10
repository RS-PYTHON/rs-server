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
import json
import threading

import pytest
import requests
from rs_server_staging.processors import (ProcessorStatus, TokenAuth,
                                          streaming_download)

#pylint: disable=undefined-variable
#pylint: disable=no-member

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
    """."""
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
        request = mocker.Mock(spec=requests.Request) #type: ignore
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
    """."""
    # mock init of s3 handler without S3_ACCESSKEY, should raise an error while creating s3 handler
    mocker.patch.dict("os.environ", {
        "S3_SECRETKEY": "fake_secret_key",
        "S3_ENDPOINT": "fake_endpoint",
        "S3_REGION": "fake_region"
    })
    with pytest.raises(ValueError, match=r"Cannot create s3 connector object."):
        streaming_download("https://example.com/product.zip", "Bearer token", "bucket/file.zip")

def test_streaming_download_runtime_error(mocker):
    """."""
    mocker.patch.dict("os.environ", {
        "S3_ACCESSKEY": "fake_access_key",
        "S3_SECRETKEY": "fake_secret_key",
        "S3_ENDPOINT": "fake_endpoint",
        "S3_REGION": "fake_region"
    })

    # mock inner s3_handler.streaming to raise
    mocker.patch("rs_server_staging.processors.S3StorageHandler.s3_streaming_upload",
                 side_effect=RuntimeError("Streaming failed"))
    # If s3-streaming raise runtime error, we forward value error? to be checked
    with pytest.raises(ValueError, match=r"Dask task failed to stream file s3://bucket/file.zip"):
        streaming_download("https://example.com/product.zip", "Bearer token", "bucket/file.zip")

class TestRSPYStaging():
    """."""
    def test_execute(self):
        """."""

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
        mock_tracker.insert.assert_called_once_with({
            "job_id": "12345",
            "status": ProcessorStatus.to_json(ProcessorStatus.QUEUED),
            "progress": 0,
            "detail": "Job is starting."
        })

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
        mock_update_default = mocker.patch.object(staging_instance.tracker, 'update', return_value=None)

        # Call log_job_execution to test status update with default attrs
        staging_instance.log_job_execution()

        # Assert that the update method was called with the correct parameters
        mock_update_default.assert_called_once_with(
            {
                "status": ProcessorStatus.to_json(ProcessorStatus.QUEUED),
                "progress": 0,
                "detail": "Job is starting."
            },
            mocker.ANY
        )
        mock_update_custom = mocker.patch.object(staging_instance.tracker, 'update', return_value=None)
        mock_query = mocker.patch('tinydb.Query', return_value=mocker.Mock())
        # Call log_job_execution to test status update with custom attrs
        staging_instance.log_job_execution(
            status=ProcessorStatus.IN_PROGRESS,
            progress=50.0,
            detail="Job is halfway done."
        )

        # Assert that the update method was called with the custom parameters
        mock_update_custom.assert_called_once_with(
            {
                "status": ProcessorStatus.to_json(ProcessorStatus.IN_PROGRESS),
                "progress": 50.0,
                "detail": "Job is halfway done."
            },
            mocker.ANY  # We can match the query condition later
        )
        assert mock_query.called_once()

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
        staging_instance.item_collection.features = [mocker.Mock(id=1), mocker.Mock(id=2)]

        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"
        staging_instance.headers = {"cookie": "test_cookie"}

        # mock all other called methods
        mock_create_streaming_list = mocker.patch.object(staging_instance, 'create_streaming_list', return_value=None)
        mock_log_job_execution = mocker.patch.object(staging_instance, 'log_job_execution', return_value=None)

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"data": "some_data"}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mocker.patch("requests.get", return_value=mock_response)

        # Call the method under test
        result = await staging_instance.check_catalog()

        # Assert that the result is True (successful catalog check)
        assert result is True

        # Construct the expected filter string
        expected_filter_string = "id IN (1, 2)"
        expected_filter_object = {
            "filter-lang": "cql2-text",
            "filter": expected_filter_string
        }
        # Assert that requests.get was called with the correct parameters
        requests.get.assert_called_once_with( #type: ignore
            f"{staging_instance.catalog_url}/catalog/search",
            headers={"cookie": "test_cookie"},
            params=json.dumps(expected_filter_object),
            timeout=3
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
            requests.exceptions.ConnectionError]:
            # mock all other called methods
            mock_log_job_execution = mocker.patch.object(staging_instance, 'log_job_execution', return_value=None)

            mocker.patch("requests.get", side_effect=possible_exception("HTTP Error"))

            # Mock the create_streaming_list method
            mock_create_streaming_list = mocker.patch.object(staging_instance, 'create_streaming_list')

            # Call the method under test
            result = await staging_instance.check_catalog()

            # Assert that the result is False (failed catalog check)
            assert result is False

            # Assert that create_streaming_list was not called during failure
            mock_create_streaming_list.assert_not_called()
            mock_log_job_execution.assert_called_once_with(ProcessorStatus.FAILED, 0, detail="Failed to search catalog")



    def test_create_streaming_list_all_downloaded(self, mocker, staging_instance):
        """Test create_streaming_list when all features are already downloaded."""
        # Set up the staging instance
        staging_instance.item_collection.features = [mocker.Mock(id=1), mocker.Mock(id=2)]

        # Create a mock catalog response indicating all features have been downloaded
        catalog_response = {
            "context": {"returned": 2},
            "features": [{"id": 1}, {"id": 2}]
        }

        # Call the method under test
        staging_instance.create_streaming_list(catalog_response)

        # Assert that stream_list is empty
        assert staging_instance.stream_list == []

    def test_create_streaming_list_no_download(self, mocker, staging_instance):
        """Test create_streaming_list when no features are found in the catalog."""
        staging_instance.item_collection.features = [mocker.Mock(id=1), mocker.Mock(id=2)]

        # Create a mock catalog response with no features found
        catalog_response = {
            "context": {"returned": 0},
            "features": []
        }

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
        catalog_response = {
            "context": {"returned": 1},
            "features": [{"id": 1}]  # Only feature 1 has been downloaded
        }

        staging_instance.create_streaming_list(catalog_response)

        # Assert that stream_list contains features 2 and 3 (not downloaded)
        assert staging_instance.stream_list == [feature_2, feature_3]

    def test_prepare_streaming_tasks_all_valid(self, mocker, staging_instance):
        """Test prepare_streaming_tasks when all assets are valid."""
        feature = mocker.Mock()
        feature.id = "feature_id"
        feature.assets = {
            "asset1": mocker.Mock(href="http://example.com/asset1", title="asset1_title"),
            "asset2": mocker.Mock(href="http://example.com/asset2", title="asset2_title"),
        }

        result = staging_instance.prepare_streaming_tasks(feature)

        # Assert that the method returns True
        assert result is True
        # Assert that assets_info has been populated correctly
        assert staging_instance.assets_info == [
            ("http://example.com/asset1", "feature_id/asset1_title"),
            ("http://example.com/asset2", "feature_id/asset2_title"),
        ]
        # Assert that asset hrefs are updated correctly
        assert feature.assets["asset1"].href == "s3://rtmpop/feature_id/asset1_title"
        assert feature.assets["asset2"].href == "s3://rtmpop/feature_id/asset2_title"


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

        # Assert that both tasks were canceled
        task_1.cancel.assert_called_once()
        task_2.cancel.assert_called_once()

    def test_delete_files_from_bucket(self):
        """."""

    def test_manage_callbacks(self):
        """."""

    def test_process_rspy_features(self):
        """."""

    def publish_rspy_feature(self):
        """."""

    def test_repr(self):
        """."""
