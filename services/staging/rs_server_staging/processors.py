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

import asyncio  # for handling asynchronous tasks
import json
import os
import threading
import time
import uuid
from enum import Enum

import requests
import tinydb  # temporary, migrate to psql
from dask.distributed import CancelledError, Client, LocalCluster, as_completed
from pygeoapi.process.base import BaseProcessor
from requests.auth import AuthBase
from rs_server_common.authentication.authentication_to_external import (
    get_station_token, load_external_auth_config_by_station_service)
from rs_server_common.s3_storage_handler.s3_storage_handler import \
    S3StorageHandler
from rs_server_common.utils.logging import Logging
from starlette.datastructures import Headers
from .rspy_models import RSPYFeatureCollectionModel
DASK_TASK_ERROR = "error"
CATALOG_BUCKET = os.environ.get("RSPY_CATALOG_BUCKET", "rs-cluster-catalog")


class ProcessorStatus(Enum):
    QUEUED = "queued"  # Request received, processor will start soon
    CREATED = "created"  # Processor has been initialised
    STARTED = "started"  # Processor execution has started
    IN_PROGRESS = "in_progress"  # Processor execution is in progress
    STOPPED = "stopped"
    FAILED = "failed"
    FINISHED = "finished"
    PAUSED = "paused"
    RESUMED = "resumed"
    CANCELLED = "cancelled"

    # Serialization
    def __str__(self):
        return self.value

    @classmethod
    def to_json(cls, status):
        if isinstance(status, cls):
            return status.value
        raise ValueError("Invalid ProcessorStatus")

    @classmethod
    def from_json(cls, value):
        for status in cls:
            if status.value == value:
                return status
        raise ValueError(f"Invalid ProcessorStatus value: {value}")


# Custom authentication class
class TokenAuth(AuthBase):
    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        # Add the Authorization header to the request
        r.headers["Authorization"] = f"Bearer {self.token}"
        r.headers["Content-Type"] = "application/x-www-form-urlencoded"
        return r


def streaming_download(product_url: str, auth: str, s3_file, s3_handler=None):
    """
        Streams a file from a product URL and uploads it to an S3-compatible storage.

        This function downloads a file from the specified `product_url` using provided 
        authentication and uploads it to an S3 bucket using a streaming mechanism. 
        If no S3 handler is provided, it initializes a default `S3StorageHandler` using 
        environment variables for credentials.

        Args:
            product_url (str): The URL of the product to download.
            auth (str): The authentication token or credentials required for the download.
            s3_file (str): The destination path/key in the S3 bucket where the file will be uploaded.
            s3_handler (S3StorageHandler, optional): An instance of a custom S3 handler for handling 
                the streaming upload. If not provided, a default handler is created.

        Returns:
            str: The S3 file path where the file was uploaded.

        Raises:
            ValueError: If the streaming process fails, raises a ValueError with details of the failure.

        Example:
            streaming_download("https://example.com/product.zip", "Bearer token", "bucket/file.zip")
    """
    try:
        if not s3_handler:
            s3_handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            )

        s3_handler.s3_streaming_upload(product_url, auth, CATALOG_BUCKET, s3_file)
    except RuntimeError as e:
        raise ValueError(f"Dask task failed to stream file s3://{s3_file}") from e
    except KeyError as exc:
        raise ValueError("Cannot create s3 connector object.") from exc
    return s3_file


class RSPYStaging(BaseProcessor):  # (metaclass=MethodWrapperMeta): - meta for stopping actions if status is failed
    status: ProcessorStatus = ProcessorStatus.QUEUED

    def __init__(
        self,
        credentials: Headers,
        input_collection: RSPYFeatureCollectionModel,
        collection: str,
        item: str,
        provider: str,
        db: tinydb.table.Table,
        cluster: LocalCluster
    ):
        """
        Initialize the RSPYStaging processor with the input collection and catalog details.

        :param input_collection: The input collection of items to process.
        :param collection: The collection to use in the catalog.
        :param item: The item to process.
        :param kwargs: Additional keyword arguments.
        """
        #################
        # Locals
        self.headers: Headers = credentials
        self.stream_list: list = []
        #################
        # Env section
        self.catalog_url: str = os.environ.get(
            "RSPY_HOST_CATALOG",
            "http://127.0.0.1:8003",
        )  # get catalog href, loopback else
        self.download_url: str = os.environ.get(
            "RSPY_RS_SERVER_CADIP_URL",
            "http://127.0.0.1:8000",
        )  # get  href, loopback else  to be removed
        #################
        # Database section
        self.job_id: str = str(uuid.uuid4())  # Generate a unique job ID
        self.detail: str = "Processing Unit was queued"
        self.progress: int = 0
        self.tracker: tinydb = db
        self.create_job_execution()
        #################
        # Inputs section
        self.item_collection: RSPYFeatureCollectionModel = input_collection
        self.catalog_collection: str = collection
        self.catalog_item_name: str = item
        self.provider: str = provider
        self.assets_info: list = []
        self.tasks: list = []
        # Lock to protect access to percentage
        self.lock = threading.Lock()
        # Tasks finished
        self.tasks_finished = 0
        self.logger = Logging.default(__name__)
        self.cluster = cluster
        self.client = None

    async def execute(self):
        self.log_job_execution(ProcessorStatus.CREATED)
        # Execution section
        await self.check_catalog()
        # Start execution
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If the loop is running, schedule the async function
            asyncio.create_task(self.process_rspy_features())
        else:
            # If the loop is not running, run it until complete
            loop.run_until_complete(self.process_rspy_features())

        return {"started": self.job_id}

    def create_job_execution(self):
        """
        Creates a new job execution entry and tracks its status.

        This method creates a job entry in the tracker with the current job's ID, status, 
        progress, and detail. The job information is stored in a persistent tracker to allow 
        monitoring and updating of the job's execution state.

        The following information is stored:
            - `job_id`: The unique identifier for the job.
            - `status`: The current status of the job, converted to a JSON-serializable format.
            - `progress`: The progress of the job execution.
            - `detail`: Additional details about the job's execution.

        Notes:
            - The `self.tracker` is expected to have an `insert` method to store the job information.
            - The status is converted to JSON using `ProcessorStatus.to_json()`.

        """
        self.tracker.insert(
            {
                "job_id": self.job_id,
                "status": ProcessorStatus.to_json(self.status),
                "progress": self.progress,
                "detail": self.detail,
            },
        )

    def log_job_execution(self, status: ProcessorStatus = None, progress: int = None, detail: str = None):
        # Update both runtime and db status and progress
        self.status = status if status else self.status
        self.progress = progress if progress else self.progress
        self.detail = detail if detail else self.detail
        tiny_job = tinydb.Query()
        self.tracker.update(
            {"status": ProcessorStatus.to_json(self.status), "progress": self.progress, "detail": self.detail},
            tiny_job.job_id == self.job_id,
        )

    async def check_catalog(self):
        # Get each feature id and create /catalog/search argument
        # Note, only for GET, to be updated and create request body for POST
        ids = [feature.id for feature in self.item_collection.features]
        # Creating the filter string
        filter_string = "id IN ({})".format(", ".join(["'{}'".format(id_) for id_ in ids]))

        # Final filter object
        filter_object = {"filter-lang": "cql2-text", "filter": filter_string}

        search_url = f"{self.catalog_url}/catalog/search"
        try:
            # forward apikey to access catalog
            # requests.get(search_url, headers=self.headers, params=filter_object, timeout=3).json()
            # not right now
            response = requests.get(search_url, params=json.dumps(filter_object), timeout=3)
            response.raise_for_status()  # Raise an error for HTTP error responses
            self.create_streaming_list(response.json())
            self.log_job_execution(ProcessorStatus.STARTED, 0, detail="Successfully searched catalog")
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            json.JSONDecodeError,
        ) as e:
            # logger.error here soon
            self.log_job_execution(ProcessorStatus.FAILED, 0, detail="Failed to search catalog")

    def create_streaming_list(self, catalog_response: dict):
        # Based on catalog response, pop out features already in catalog and prepare rest for download
        if catalog_response["context"]["returned"] == len(self.item_collection.features):
            self.stream_list = []
        else:
            if not catalog_response["features"]:
                # No search result found, process everything from self.item_collection
                self.stream_list = self.item_collection.features
            else:
                # Do the difference, call rs-server-download only with features to be downloaded
                # Extract IDs from the catalog response directly
                already_downloaded_ids = {feature["id"] for feature in catalog_response["features"]}
                # Select only features whose IDs have not already been downloaded (returned in /search)
                not_downloaded_features = [
                    item for item in self.item_collection.features if item.id not in already_downloaded_ids
                ]
                self.stream_list = not_downloaded_features

    def prepare_streaming_tasks(self, feature):
        """Prepare tasks for the given feature to the Dask cluster.

        Args:
            feature: The feature containing assets to download.

        Returns:
            True if the info has been constructed, False otherwise
        """

        for _, asset_content in feature.assets.items():
            try:
                asset = asset_content.dict()
                product_url = asset.get("href")
                product_name = asset.get("title")
                s3_obj_path = f"{feature.id.rstrip('/')}/{product_name}"
                self.assets_info.append((product_url, s3_obj_path))
            except KeyError as e:
                self.logger.error(f"Error: Missing href or title in asset dictionary {e}")
                return False

        return True

    def handle_task_failure(self, error):
        """Handle failures during task processing, including cancelling tasks and cleaning up S3 objects.

        Args:
            error (Exception): The exception that occurred.
            tasks (list): List of Dask task futures.
            s3_objs (list): List of S3 object paths to clean up.
        """
        # with self.lock:
        #     self.callbacks_disabled = True
        self.logger.error(
            "Error during staging. Canceling all the remaining tasks. "
            "The assets already copied to the bucket will be deleted."
            f"The error: {error}",
        )

        # Cancel remaining tasks
        for task in self.tasks:
            try:
                if not task.done():
                    self.logger.info("Canceling task %s status %s", task.key, task.status)
                    task.cancel()
            except CancelledError as e:
                self.logger.error("Task was already cancelled: %s", e)

    def delete_files_from_bucket(self, bucket):
        """
        Deletes partial or fully copied files from the specified S3 bucket.

        This method iterates over the assets listed in `self.assets_info` and deletes 
        them from the given S3 bucket. If no assets are present, the method returns 
        without performing any actions. The S3 connection is established using credentials 
        from environment variables.

        Args:
            bucket (str): The name of the S3 bucket from which to delete the files.

        Raises:
            RuntimeError: If there is an issue deleting a file from the S3 bucket.

        Logs:
            - Logs an error if the S3 handler initialization fails.
            - Logs exceptions if an error occurs while trying to delete a file from S3.

        Notes:
            - The `self.assets_info` attribute is expected to be a list of asset information,
            with each entry containing details for deletion.
            - The S3 credentials (access key, secret key, endpoint, and region) are fetched
            from environment variables: `S3_ACCESSKEY`, `S3_SECRETKEY`, `S3_ENDPOINT`, 
            and `S3_REGION`.
        """
        if not self.assets_info:
            self.logger.debug("Trying to remove file from bucket, but no asset info defined.")
            return
        try:
            s3_handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            )
            if not s3_handler:
                self.logger.error("Error when trying to to delete files from the s3 bucket")
                return
            for s3_obj in self.assets_info:
                s3_handler.delete_file_from_s3(bucket, s3_obj[1])
                self.logger.debug("Deleted s3://%s/%s", CATALOG_BUCKET, s3_obj[1])
        except RuntimeError as e:
            self.logger.error("Error when trying to delete s3://%s/%s . Exception: %s", bucket, s3_obj[1], e)
        except KeyError as exc:
            self.logger.error("Cannot connect to s3 storage, %s", exc)

    def manage_callbacks(self):
        if not self.client:
            return
        for task in as_completed(self.tasks):
            try:
                task.result()  # This will raise the exception from the task if it failed
                self.tasks_finished += 1
                self.log_job_execution(
                    ProcessorStatus.IN_PROGRESS,
                    (self.tasks_finished * 100 / len(self.tasks)),
                    detail="In progress",
                )
                self.logger.debug("%s Task streaming completed", task.key)
            except Exception as task_e:  # pylint: disable=broad-exception-caught
                self.logger.error("Task failed with exception: %s", task_e)
                self.handle_task_failure(task_e)
                # Wait for all the current running tasks to complete.
                # TODO: The timeout should be configurable
                timeout = 500
                while timeout > 0:
                    self.logger.debug("Client stack_call = %s", self.client.call_stack())
                    if not self.client.call_stack():
                        break
                    time.sleep(1)
                    timeout -= 1
                # Update status for the job
                self.log_job_execution(ProcessorStatus.FAILED, None, detail="At least one of the tasks failed")
                self.delete_files_from_bucket(CATALOG_BUCKET)

                return

        # Publish all the features once processed
        for feature in self.stream_list:
            self.publish_rspy_feature(feature)

        # Update status once all features are processed
        self.log_job_execution(ProcessorStatus.FINISHED, 100, detail="Finished")

    async def process_rspy_features(self):
        # Process each feature, by starting streaming download of its assets to final bucket
        self.log_job_execution(ProcessorStatus.IN_PROGRESS, 0, detail="Sending tasks to the dask cluster")
        for feature in self.stream_list:
            if not self.prepare_streaming_tasks(feature):
                self.log_job_execution(ProcessorStatus.FAILED, 0, detail="No tasks created")

        # retrieve token
        token = get_station_token(
            load_external_auth_config_by_station_service(self.provider.lower(), self.provider),
        )

        self.client = Client(self.cluster, asynchronous=True)
        # Check the cluster dashboard
        # self.logger.debug(f"Cluster dashboard: {self.cluster.dashboard_link}")
        self.tasks = []
        # Submit tasks
        for asset_info in self.assets_info:

            self.tasks.append(self.client.submit(streaming_download, asset_info[0], TokenAuth(token), asset_info[1]))
        # starting another thread for managing the dask callbacks
        try:
            await asyncio.to_thread(self.manage_callbacks)
        except Exception as e: # pylint: disable=broad-exception-caught
            self.logger.debug("Exception caught: %s", e)
        self.assets_info = []
        self.client.close()
        self.client = None

    def publish_rspy_feature(self, feature: dict):
        """
        Publishes a given feature to the RSPY catalog.

        This method sends a POST request to the catalog API to publish a feature (in the form 
        of a dictionary) to a specified collection. The feature is serialized into JSON format 
        and published to the `/catalog/collections/{collectionId}/items` endpoint.

        Args:
            feature (dict): The feature to be published, represented as a dictionary. It should 
            include all necessary attributes required by the catalog.

        Returns:
            bool: Returns `True` if the feature was successfully published, otherwise returns `False` 
            in case of an error.

        Raises:
            requests.exceptions.HTTPError: Raised if the server returns an HTTP error response.
            requests.exceptions.Timeout: Raised if the request times out.
            requests.exceptions.RequestException: Raised for general request issues.
            requests.exceptions.ConnectionError: Raised if there's a connection error.
            json.JSONDecodeError: Raised if the response cannot be decoded as JSON.

        Logging:
            - Logs an error message with details if the request fails.
            - Logs the job status as `ProcessorStatus.FAILED` if the feature publishing fails.
            - Calls `self.delete_files_from_bucket()` to clean up related files in case of failure.

        Notes:
            - The `catalog_url` and `catalog_collection` attributes should be defined in the instance.
            - The method assumes that API keys or other authorization mechanisms are handled at the 
            request level, though user information is not directly required.
            - Timeout for the request is set to 3 seconds.
        """
        # Publish feature to catalog
        # how to get user? // Do we need user? should /catalog/collection/collectionId/items works with apik?
        publish_url = f"{self.catalog_url}/catalog/collections/{self.catalog_collection}/items"
        try:
            response = requests.post(publish_url, data=feature.json(), timeout=3)
            response.raise_for_status()  # Raise an error for HTTP error responses
            return True
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            json.JSONDecodeError,
        ) as exc:
            self.logger.error("Error while publishing items to rspy catalog %s", exc)
            self.log_job_execution(ProcessorStatus.FAILED)
            self.delete_files_from_bucket(CATALOG_BUCKET)
            return False

    def __repr__(self):
        """Returns a string representation of the RSPYStaging processor."""
        return "RSPY Staging OGC API Processor"


# Register the processor
processors = {"RSPYStaging": RSPYStaging}
