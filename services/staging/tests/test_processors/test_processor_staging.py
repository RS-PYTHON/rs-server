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
from dask_gateway import Gateway
from pygeoapi.util import JobStatus
from rs_server_staging.processors.processor_staging import Staging
from rs_server_staging.utils.asset_info import AssetInfo

# pylint: disable=undefined-variable
# pylint: disable=too-many-lines


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
        mock_datetime = mocker.patch("rs_server_staging.processors.processor_staging.datetime")
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
        staging_instance.assets_info = [AssetInfo("fake_asset_href", "fake_s3_path", "fake_bucket")]
        # Mock S3StorageHandler and its delete_file_from_s3 method
        mock_s3_handler = mocker.Mock()
        mocker.patch("rs_server_staging.processors.processor_staging.S3StorageHandler", return_value=mock_s3_handler)
        # Call the delete_files_from_bucket method
        staging_instance.delete_files_from_bucket()
        # Assert that S3StorageHandler was instantiated with the correct environment variables
        mock_s3_handler.delete_file_from_s3.assert_called_once_with("fake_bucket", "fake_s3_path")

    def test_delete_files_from_bucket_empty(self, mocker, staging_instance: Staging):
        """Test delete files with no assets, nothing should happen."""
        staging_instance.assets_info = []
        # Mock S3StorageHandler to ensure it's not used
        mock_s3_handler = mocker.Mock()
        mocker.patch("rs_server_staging.processors.processor_staging.S3StorageHandler", return_value=mock_s3_handler)
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
        staging_instance.assets_info = [AssetInfo("fake_asset_href", "fake_s3_path", "fake_bucket")]
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
        staging_instance.assets_info = [AssetInfo("fake_asset_href", "fake_s3_path", "fake_bucket")]
        # Mock S3StorageHandler and raise a RuntimeError
        mock_s3_handler = mocker.Mock()
        mock_s3_handler.delete_file_from_s3.side_effect = RuntimeError("Fake runtime error")
        mocker.patch("rs_server_staging.processors.processor_staging.S3StorageHandler", return_value=mock_s3_handler)
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
        mock_client = mocker.patch(
            "rs_server_staging.processors.processor_staging.Client",
            autospec=True,
            return_value=None,
        )

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
        """Test to mock managing of successful tasks"""
        # Mock tasks that will succeed
        task1 = mocker.Mock()
        task1.result = mocker.Mock(return_value="simultated_filename_1")  # Simulate a successful task
        task1.key = "task1"

        task2 = mocker.Mock()
        task2.result = mocker.Mock(return_value="simultated_filename_2")  # Simulate another successful task
        task2.key = "task2"

        # mock distributed as_completed
        mocker.patch("rs_server_staging.processors.processor_staging.as_completed", return_value=iter([task1, task2]))
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
        mocker.patch("rs_server_staging.processors.processor_staging.as_completed", return_value=iter([task1, task2]))
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
        mocker.patch("rs_server_staging.processors.processor_staging.as_completed", return_value=iter([task1, task2]))
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
        mocker.patch("rs_server_staging.processors.processor_staging.prepare_streaming_tasks", return_value=None)

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
        mocker.patch("rs_server_staging.processors.processor_staging.prepare_streaming_tasks", return_value=[])

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
        mocker.patch("rs_server_staging.processors.processor_staging.prepare_streaming_tasks", return_value=[])
        staging_instance.assets_info = [AssetInfo("some_asset", "fake_s3_path", "fake_bucket")]

        # Mock token retrieval
        mocker.patch(
            "rs_server_staging.processors.processor_staging.load_external_auth_config_by_domain",
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
        mocker.patch("rs_server_staging.processors.processor_staging.prepare_streaming_tasks", return_value=[])

        # Mock token retrieval
        mocker.patch(
            "rs_server_staging.processors.processor_staging.load_external_auth_config_by_domain",
            return_value=mocker.Mock(),
        )

        # Mock the external auth configuration
        config.trusted_domains = ["test_trusted.example"]  # Set the trusted_domains member
        mocker.patch(
            "rs_server_staging.processors.processor_staging.load_external_auth_config_by_domain",
            return_value=config,
        )

        # Mock Dask cluster client
        mocker.patch.object(staging_instance, "dask_cluster_connect", return_value=client)

        # Mock update_station_token
        mocker.patch(
            "rs_server_staging.processors.processor_staging.update_station_token",
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
