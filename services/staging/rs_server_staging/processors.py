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
"""Base RSPY Stagging processor."""

import asyncio  # for handling asynchronous tasks
import json
import os
import time
import uuid
from datetime import datetime
from typing import Union

import requests
from dask.distributed import CancelledError, Client, LocalCluster, as_completed
from dask_gateway import Gateway, JupyterHubAuth
from fastapi import HTTPException
from pygeoapi.process.base import BaseProcessor
from pygeoapi.process.manager.postgresql import PostgreSQLManager
from requests.auth import AuthBase
from rs_server_common.authentication.authentication_to_external import (
    get_station_token,
    load_external_auth_config_by_station_service,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from rs_server_common.utils.logging import Logging
from starlette.datastructures import Headers
from starlette.requests import Request

from .rspy_models import Feature, FeatureCollectionModel
from .staging_job_status import EStagingStatus


# Custom authentication class
class TokenAuth(AuthBase):
    """Custom authentication class

    Args:
        AuthBase (ABC): Base auth class
    """

    def __init__(self, token: str):
        """Init token auth

        Args:
            token (str): Token value
        """
        self.token = token

    def __call__(self, request: Request):  # type: ignore
        """Add the Authorization header to the request

        Args:
            request (Request): request to be modified

        Returns:
            Request: request with modified headers
        """
        request.headers["Authorization"] = f"Bearer {self.token}"  # type: ignore
        return request

    def __repr__(self) -> str:
        return "RSPY Token handler"


def streaming_task(product_url: str, trusted_domains: list[str], auth: str, bucket: str, s3_file: str):
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

    Returns:
        str: The S3 file path where the file was uploaded.

    Raises:
        ValueError: If the streaming process fails, raises a ValueError with details of the failure.
    """

    try:
        s3_handler = S3StorageHandler(
            os.environ["S3_ACCESSKEY"],
            os.environ["S3_SECRETKEY"],
            os.environ["S3_ENDPOINT"],
            os.environ["S3_REGION"],
        )
        s3_handler.s3_streaming_upload(product_url, trusted_domains, auth, bucket, s3_file)
    except RuntimeError as e:
        raise ValueError(
            f"Dask task failed to stream file from {product_url} to s3://{bucket}/{s3_file}. Reason: {e}",
        ) from e
    except KeyError as exc:
        raise ValueError(f"Cannot create s3 connector object. Reason: {exc}") from exc
    return s3_file


class Staging(BaseProcessor):  # (metaclass=MethodWrapperMeta): - meta for stopping actions if status is failed
    """
    RSPY staging implementation, the processor should perform the following actions after being triggered:

    • First, the RSPY catalog is searched to determine if some or all of the input features have already been staged.

    • If all features are already staged, the process should return immediately.

    • If there are features that haven’t been staged, the processor connects to a specified Dask cluster as a client.

    • Once connected, the processor begins asynchronously streaming each feature directly into the rs-cluster-catalog
    bucket using a Dask-distributed process.

    • The job status is updated after each feature is processed, and overall progress can be tracked via the
    /jobs/{job-id} endpoint.

    • Upon successful completion of the streaming process, the processor publishes the features to the RSPY catalog.

    • If an error occurs at any point during the streaming or publishing process, the operation is rolled back and an
    appropriate error message is displayed.

    Args:
        BaseProcessor (OGCAPI): Base OGC API processor class
    Returns:
        JSON: JSON containing job_id for tracking.
    """

    def __init__(
        self,
        credentials: Request,
        input_collection: FeatureCollectionModel,
        collection: str,
        item: str,
        provider: str,
        db_process_manager: PostgreSQLManager,
        cluster: LocalCluster,
    ):  # pylint: disable=super-init-not-called
        """
        Initialize the Staging processor with credentials, input collection, catalog details,
        database, and cluster configuration.

        Args:
            credentials (Headers): Authentication headers used for requests.
            input_collection (FeatureCollectionModel): The input collection of RSPY features to process.
            collection (str): The name of the collection from the catalog to use.
            item (str): The specific item to process within the collection.
            provider (str): The name of the provider offering the data for processing.
            db_process_manager (PostgreSQLManager): The pygeoapi Postgresql Manager used to track job execution
                status and metadata.
            cluster (LocalCluster): The Dask LocalCluster instance used to manage distributed computation tasks.

        Attributes:
            headers (Headers): Stores the provided authentication headers.
            stream_list (list): A list to hold streaming information for processing.
            catalog_url (str): URL of the catalog service, fetched from environment or default value.
            download_url (str): URL of the RS server, fetched from environment or default value.
            job_id (str): A unique identifier for the processing job, generated using UUID.
            detail (str): Status message describing the current state of the processing unit.
            progress (int): Integer tracking the progress of the current job.
            item_collection (FeatureCollectionModel): Holds the input collection of features.
            catalog_collection (str): Name of the catalog collection.
            catalog_item_name (str): Name of the specific item in the catalog being processed.
            provider (str): The data provider for the current processing task.
            assets_info (list): Holds information about assets associated with the processing.
            tasks (list): List of tasks to be executed for processing.
            lock (threading.Lock): A threading lock to synchronize access to shared resources.
            tasks_finished (int): Tracks the number of tasks completed.
            logger (Logger): Logger instance for capturing log output.
            cluster (LocalCluster): Dask LocalCluster instance managing computation resources, used in local mode
                If this is None, it means we are in cluster mode, and we should dynamically connect
                to the Dask cluster for each job.
        """
        #################
        # Locals
        self.headers: Headers = credentials.headers
        self.stream_list: list = []
        #################
        # Env section
        self.catalog_url: str = os.environ.get(
            "RSPY_HOST_CATALOG",
            "http://127.0.0.1:8003",
        )  # get catalog href, loopback else
        #################
        # Database section
        self.job_id: str = str(uuid.uuid4())  # Generate a unique job ID
        self.detail: str = "Processing Unit was created"
        self.progress: float = 0.0
        self.db_process_manager = db_process_manager
        self.status = EStagingStatus.QUEUED
        self.create_job_execution()
        #################
        # Inputs section
        self.item_collection: FeatureCollectionModel = input_collection
        self.catalog_collection: str = collection
        self.catalog_item_name: str = item
        self.provider: str = provider
        self.assets_info: list = []
        self.tasks: list = []
        # Tasks finished
        self.tasks_finished = 0
        self.logger = Logging.default(__name__)
        self.cluster = cluster
        self.catalog_bucket = os.environ.get("RSPY_CATALOG_BUCKET", "rs-cluster-catalog")

    # Override from BaseProcessor, execute is async in RSPYProcessor
    async def execute(self):  # pylint: disable=arguments-differ, invalid-overridden-method
        """
        Asynchronously execute the RSPY staging process, starting with a catalog check and
        proceeding to feature processing if the check succeeds.

        This method first logs the creation of a new job execution and verifies the connection to
        the catalog service. If the catalog connection fails, it logs an error and stops further
        execution. If the connection is successful, it initiates the asynchronous processing of
        RSPY features.

        If the current event loop is running, the feature processing task is scheduled asynchronously.
        Otherwise, the event loop runs until the processing task is complete.

        Returns:
            dict: A dictionary containing the job ID and a status message indicating the job
                has started.
                Example: {"started": <job_id>}

        Logs:
            EStagingStatus.CREATED: Logs the creation of a new processing job.
            Error: Logs an error if connecting to the catalog service fails.

        Raises:
            None: This method doesn't raise any exceptions directly but logs errors if the
                catalog check fails.
        """
        # Check for the proper input
        # Check if item collection is provided
        if not self.item_collection or not hasattr(self.item_collection, "features"):
            self.log_job_execution(
                EStagingStatus.FINISHED,
                0,
                detail="No valid items were provided in the input for staging",
            )
            return {"finished": self.job_id}

        # Filter out features with no assets
        self.item_collection.features = [feature for feature in self.item_collection.features if feature.assets]

        # Check if any features with assets remain
        if not self.item_collection.features:
            self.log_job_execution(
                EStagingStatus.FINISHED,
                0,
                detail="No items with assets were found in the input for staging",
            )
            return {"finished": self.job_id}

        # set the CREATED status for the job
        self.log_job_execution(EStagingStatus.CREATED)
        # Execution section
        if not await self.check_catalog():
            self.logger.error(
                f"Failed to start the staging process. Checking the collection '{self.catalog_collection}' failed !",
            )
            self.log_job_execution(
                EStagingStatus.FAILED,
                0,
                detail="Failed to start the staging process. "
                f"Checking the collection '{self.catalog_collection}' failed !",
            )
            return {"failed": self.job_id}
        self.log_job_execution(EStagingStatus.STARTED, 0, detail="Successfully searched catalog")
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
            - The status is converted to JSON using `EStagingStatus.to_json()`.

        """
        job_metadata = {
            "identifier": self.job_id,
            "status": self.status.value.upper(),
            "progress": self.progress,
            "detail": self.detail,
        }
        self.db_process_manager.add_job(job_metadata)

    def log_job_execution(
        self,
        status: Union[EStagingStatus, None] = None,
        progress: Union[float, None] = None,
        detail: Union[str, None] = None,
    ):
        """Method used to log progress into db."""
        # Update both runtime and db status and progress

        self.status = status if status else self.status
        self.progress = progress if progress else self.progress
        self.detail = detail if detail else self.detail

        update_data = {
            "status": self.status.value.upper(),
            "progress": self.progress,
            "detail": self.detail,
            "updated_at": datetime.now(),  # Update updated_at each time a change is made
        }
        self.db_process_manager.update_job(self.job_id, update_data)

    async def check_catalog(self):
        """
        Method used to check RSPY catalog if a feature from input_collection is already published.
        """
        # Set the filter containing the item ids to be inserted
        # Get each feature id and create /catalog/search argument
        ids = [feature.id for feature in self.item_collection.features]
        stry = []
        for id_ in ids:
            stry.append(f"'{id_}'")
        # Creating the filter string
        filter_string = f"id IN ({', '.join(stry)})"

        # Final filter object
        filter_object = {"filter-lang": "cql2-text", "filter": filter_string, "limit": str(len(ids))}

        search_url = f"{self.catalog_url}/catalog/collections/{self.catalog_collection}/search"

        # Another method is to get all the items and loop with them to match item ids
        # search_url = f"{self.catalog_url}/catalog/collections/{self.catalog_collection}/items"

        try:
            response = requests.get(
                search_url,
                headers={"cookie": self.headers.get("cookie", None)},
                params=filter_object,
                timeout=5,
            )
            response.raise_for_status()  # Raise an error for HTTP error responses
            # check the response type
            item_collection = response.json()
            if not item_collection.get("type") or item_collection.get("type") != "FeatureCollection":
                self.logger.error("Failed to search catalog, no expected response received")
                return False
            # for debugging only
            for item in item_collection.get("features"):
                self.logger.debug(f"Session {item.get('id')} has {len(item.get('assets'))} assets")
            # end of TODO
            self.create_streaming_list(item_collection)
            return True
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            json.JSONDecodeError,
            RuntimeError,
        ) as exc:
            self.logger.error(f"Failed to search catalog: {exc}")
            self.log_job_execution(EStagingStatus.FAILED, 0, detail=f"Failed to search catalog: {exc}")
            return False

    def create_streaming_list(self, catalog_response: dict):
        """
        Prepares a list of items for download based on the catalog response.

        This method compares the features in the provided `catalog_response` with the features
        already present in `self.item_collection.features`. If all features have been returned
        in the catalog response, the streaming list is cleared. Otherwise, it determines which
        items are not yet downloaded and updates `self.stream_list` with those items.

        Args:
            catalog_response (dict): A dictionary response from a catalog search.

        Behavior:
            - If the number of items in `catalog_response["context"]["returned"]` matches the
            total number of items in `self.item_collection.features`, `self.stream_list`
            is set to an empty list, indicating that there are no new items to download.
            - If the `catalog_response["features"]` is empty (i.e., no items were found in the search),
            it assumes no items have been downloaded and sets `self.stream_list` to all features
            in `self.item_collection.features`.
            - Otherwise, it computes the difference between the items in `self.item_collection.features`
            and the items already listed in the catalog response, updating `self.stream_list` to
            contain only those that have not been downloaded yet.

        Side Effects:
            - Updates `self.stream_list` with the features that still need to be downloaded.

        """
        # Based on catalog response, pop out features already in catalog and prepare rest for download
        try:
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
        except KeyError as ke:
            self.logger.exception(
                "The 'features' field is missing in the response from the catalog service. "
                f"Unable to check the collection {self.catalog_collection}. {ke}",
            )
            raise RuntimeError(
                "The 'features' field is missing in the response from the catalog service. ",
            ) from ke

    def prepare_streaming_tasks(self, feature):
        """Prepare tasks for the given feature to the Dask cluster.

        Args:
            feature: The feature containing assets to download.

        Returns:
            True if the info has been constructed, False otherwise
        """

        for asset_name, asset_content in feature.assets.items():
            if not asset_content.href or not asset_name:
                self.logger.error("Missing href or title in asset dictionary")
                return False
            # Add the user_collection as main directory, as soon as the authentication will be
            # implemented in this staging process
            s3_obj_path = f"{self.catalog_collection}/{feature.id.rstrip('/')}/{asset_name}"
            self.assets_info.append((asset_content.href, s3_obj_path))
            # update the s3 path, this will be checked in the rs-server-catalog in the
            # publishing phase
            asset_content.href = f"s3://rtmpop/{s3_obj_path}"
            feature.assets[asset_name] = asset_content
        return True

    def handle_task_failure(self, error):
        """Handle failures during task processing, including cancelling tasks and cleaning up S3 objects.

        Args:
            error (Exception): The exception that occurred.
        """

        self.logger.error(
            "Error during staging. Canceling all the remaining tasks. "
            "The assets already copied to the bucket will be deleted."
            "The error: %s",
            error,
        )

        # Cancel remaining tasks
        for task in self.tasks:
            try:
                if not task.done():
                    self.logger.info("Canceling task %s status %s", task.key, task.status)
                    task.cancel()
            except CancelledError as e:
                self.logger.error("Task was already cancelled: %s", e)

    def delete_files_from_bucket(self):
        """
        Deletes partial or fully copied files from the specified S3 bucket.

        This method iterates over the assets listed in `self.assets_info` and deletes
        them from the given S3 bucket. If no assets are present, the method returns
        without performing any actions. The S3 connection is established using credentials
        from environment variables.

        Raises:
            RuntimeError: If there is an issue deleting a file from the S3 bucket.

        Logs:
            - Logs an error if the S3 handler initialization fails.
            - Logs exceptions if an error occurs while trying to delete a file from S3.

        Notes:
            - The `self.assets_info` attribute is expected to be a list of asset information,
            with each entry containing details for deletion.
            - The `self.catalog_bucket` is expected to be already set from init
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

            for s3_obj in self.assets_info:
                try:
                    s3_handler.delete_file_from_s3(self.catalog_bucket, s3_obj[1])
                except RuntimeError as re:
                    self.logger.warning(
                        "Failed to delete from the bucket key s3://%s/%s : %s",
                        self.catalog_bucket,
                        s3_obj[1],
                        re,
                    )
                    continue
        except KeyError as exc:
            self.logger.error("Cannot connect to s3 storage, %s", exc)

    def manage_dask_tasks_results(self, client):
        """
        Method used to manage dask tasks.

        As job are completed, progress is dinamically incremented and monitored into DB.
        If a single tasks fails:
            - handle_task_failure() is called
            - processor waits (RSPY_STAGING_TIMEOUT or 600 seconds) untill running tasks are finished
            - the execution of future tasks is canceled.
            - When all streaming tasks are finished, processor removes all files streamed in s3 bucket.
        """
        self.logger.info("Tasks monitoring started")
        if not client:
            self.logger.error("The dask cluster client object is not created. Exiting")
            return
        for task in as_completed(self.tasks):
            try:
                task.result()  # This will raise the exception from the task if it failed
                self.tasks_finished += 1
                self.log_job_execution(
                    EStagingStatus.IN_PROGRESS,
                    round((self.tasks_finished * 100 / len(self.tasks)), 2),
                    detail="In progress",
                )
                self.logger.debug("%s Task streaming completed", task.key)
            except Exception as task_e:  # pylint: disable=broad-exception-caught
                self.logger.error("Task failed with exception: %s", task_e)
                self.handle_task_failure(task_e)
                # Wait for all the current running tasks to complete.
                timeout = int(os.environ.get("RSPY_STAGING_TIMEOUT", 600))
                while timeout > 0:
                    self.logger.debug("Client stack_call = %s", client.call_stack())
                    if not client.call_stack():
                        # Break loop when dask client call stack is empty (No tasks are running)
                        break
                    time.sleep(1)
                    timeout -= 1
                # Update status for the job
                self.log_job_execution(
                    EStagingStatus.FAILED,
                    None,
                    detail=f"At least one of the tasks failed: {task_e}",
                )
                self.delete_files_from_bucket()
                self.logger.error(f"Tasks monitoring finished with error. At least one of the tasks failed: {task_e}")
                return
        # Publish all the features once processed
        published_featurs_ids: list[str] = []
        for feature in self.stream_list:
            if not self.publish_rspy_feature(feature):
                # cleanup
                self.log_job_execution(
                    EStagingStatus.FAILED,
                    None,
                    detail=f"The item {feature.id} couldn't be " "published in the catalog. Cleaning up",
                )
                # delete the files
                self.delete_files_from_bucket()
                # delete the published items
                self.unpublish_rspy_features(published_featurs_ids)
                return
            published_featurs_ids.append(feature.id)
        # Update status once all features are processed
        self.log_job_execution(EStagingStatus.FINISHED, 100, detail="Finished")
        self.logger.info("Tasks monitoring finished")

    def dask_cluster_connect(self):
        """Connects a dask cluster scheduler
        Establishes a connection to a Dask cluster, either in a local environment or via a Dask Gateway in
        a Kubernetes cluster. This method checks if the cluster is already created (for local mode) or connects
        to a Dask Gateway to find or create a cluster scheduler (for Kubernetes mode, see RSPY_LOCAL_MODE env var).

        1. **Local Mode**:
        - If `self.cluster` already exists, it assumes the Dask cluster was created when the application started,
            and proceeds without creating a new cluster.

        2. **Kubernetes Mode**:
        - If `self.cluster` is not already defined, the method attempts to connect to a Dask Gateway
            (using environment variables `DASK_GATEWAY__ADDRESS` and `DASK_GATEWAY__AUTH__TYPE`) to
            retrieve a list of existing clusters.
        - If no clusters are available, it attempts to create a new cluster scheduler.

        Args:
            None

        Raises:
            RuntimeError: Raised if the cluster name is None, required environment variables are missing,
                        cluster creation fails or authentication errors occur.
            KeyError: Raised if the necessary Dask Gateway environment variables (`DASK_GATEWAY__ADDRESS`,
                `DASK_GATEWAY__AUTH__TYPE`, `RSPY_DASK_STAGING_CLUSTER_NAME`, `JUPYTERHUB_API_TOKEN` ) are not set.
            IndexError: Raised if no clusters are found in the Dask Gateway and new cluster creation is attempted.
            dask_gateway.exceptions.GatewayServerError: Raised when there is a server-side error in Dask Gateway.
            dask_gateway.exceptions.AuthenticationError: Raised if authentication to the Dask Gateway fails.
            dask_gateway.exceptions.ClusterLimitExceeded: Raised if the limit on the number of clusters is exceeded.

        Behavior:
        1. **Cluster Creation and Connection**:
            - In Kubernetes mode, the method tries to connect to an existing cluster or creates
            a new one if none exists.
            - Error handling includes catching issues like missing environment variables, authentication failures,
            cluster creation timeouts, or exceeding cluster limits.

        2. **Logging**:
            - Logs the list of available clusters if connected via the Dask Gateway.
            - Logs the success of the connection or any errors encountered during the process.
            - Logs the Dask dashboard URL and the number of active workers.

        3. **Client Initialization**:
            - Once connected to the Dask cluster, the method creates a Dask `Client` object for managing tasks
            and logs the number of running workers.
            - If no workers are found, it scales the cluster to 1 worker.

        4. **Error Handling**:
            - Handles various exceptions during the connection and creation process, including:
            - Missing environment variables.
            - Failures during cluster creation.
            - Issues related to cluster scaling, worker retrieval, or client creation.
            - If an error occurs, the method logs the error and attempts to gracefully handle failure.

        Returns:
            None
        """

        # If self.cluster is already initialized, it means the application is running in local mode, and
        # the cluster was created when the application started.
        if not self.cluster:
            # in kubernetes cluster mode, we have to connect to the gateway and get the list of the clusters
            try:
                # get the name of the cluster
                cluster_name = os.environ["RSPY_DASK_STAGING_CLUSTER_NAME"]
                # check the auth type, only jupyterhub type supported for now
                auth_type = os.environ["DASK_GATEWAY__AUTH__TYPE"]
                # Handle JupyterHub authentication
                if auth_type == "jupyterhub":
                    gateway_auth = JupyterHubAuth(api_token=os.environ["JUPYTERHUB_API_TOKEN"])
                else:
                    self.logger.error(f"Unsupported authentication type: {auth_type}")
                    raise RuntimeError(f"Unsupported authentication type: {auth_type}")
                gateway = Gateway(
                    address=os.environ["DASK_GATEWAY__ADDRESS"],
                    auth=gateway_auth,
                )
                clusters = gateway.list_clusters()
                self.logger.debug(f"The list of clusters: {clusters}")

                # Get the identifier of the cluster whose name is equal to the cluster_name variable
                # Protection for the case when this cluster does not exit
                cluster_id = next(
                    (
                        cluster.name
                        for cluster in clusters
                        if isinstance(cluster.options, dict) and cluster.options.get("cluster_name") == cluster_name
                    ),
                    None,
                )

                if not cluster_id:
                    raise IndexError(f"No dask cluster named '{cluster_name}' was found.")

                self.cluster = gateway.connect(cluster_id)

                self.logger.info(f"Successfully connected to the {cluster_name} dask cluster")
            except KeyError as e:
                self.logger.exception(
                    "Failed to retrieve the required connection details for "
                    "the Dask Gateway from one or more of the following environment variables: "
                    "DASK_GATEWAY__ADDRESS, RSPY_DASK_STAGING_CLUSTER_NAME, "
                    f"JUPYTERHUB_API_TOKEN, DASK_GATEWAY__AUTH__TYPE. {e}",
                )

                raise RuntimeError from e
            except IndexError as e:
                self.logger.exception(f"Failed to find the specified dask cluster: {e}")
                raise RuntimeError(f"No dask cluster named '{cluster_name}' was found.") from e

        self.logger.debug("Cluster dashboard: %s", self.cluster.dashboard_link)
        # create the client as well
        client = Client(self.cluster)

        # This is a temporary fix for the dask cluster settings which does not create a scheduler by default
        # This code should be removed as soon as this is fixed in the kubernetes cluster
        try:
            self.logger.debug(f"{client.get_versions(check=True)}")
            workers = client.scheduler_info()["workers"]
            self.logger.info(f"Number of running workers: {len(workers)}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.exception(f"Dask cluster client failed: {e}")
            raise RuntimeError(f"Dask cluster client failed: {e}") from e
        if len(workers) == 0:
            self.logger.info("No workers are currently running in the Dask cluster. Scaling up to 1.")
            self.cluster.scale(1)
        # end of TODO

        # Check the cluster dashboard
        self.logger.debug(f"Dask Client: {client} | Cluster dashboard: {self.cluster.dashboard_link}")

        return client

    def submit_tasks_to_dask_cluster(self, token: str, trusted_domains: list[str], client: Client):
        """Submits multiple tasks to a Dask cluster for asynchronous processing.

        Each task involves downloading a file stream (using `streaming_task`) and uploading it to an S3 bucket
        or similar storage, authenticated using the provided token.

        The function iterates through a list of assets (created previously after checking the catalog), represented by
        `self.assets_info`, and submits a Dask task for each asset to the cluster. Tasks are appended to `self.tasks`
        for later monitoring.

        Args:
            token (str): Authentication token used for accessing and processing the asset download
            from the external station (wrapped in `TokenAuth`).
            client (Client): The dask cluster client created in the dask_cluster_connect function

        Raises:
            None directly (all exceptions are caught and logged).

        Returns:
            None

        Exceptions:
            - **Generic Exception**: Catches all exceptions during task submission
        """
        # empty the list
        self.tasks = []
        # Submit tasks
        try:
            for asset_info in self.assets_info:
                self.tasks.append(
                    client.submit(
                        streaming_task,
                        asset_info[0],
                        trusted_domains,
                        TokenAuth(token),
                        self.catalog_bucket,
                        asset_info[1],
                    ),
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.exception(f"Submitting task to dask cluster failed. Reason: {e}")
            raise RuntimeError(f"Submitting task to dask cluster failed. Reason: {e}") from e

    async def process_rspy_features(self):
        """
        Method used to trigger dask distributed streaming process.
        It creates dask client object, gets the external data sources access token
        Prepares the tasks for execution
        Manage eventual runtime exceptions
        """
        self.logger.debug("Starting main loop")

        # Process each feature by initiating the streaming download of its assets to the final bucket.
        for feature in self.stream_list:
            if not self.prepare_streaming_tasks(feature):
                self.log_job_execution(EStagingStatus.FAILED, 0, detail="Unable to create tasks for the Dask cluster")
                return
        if not self.assets_info:
            self.log_job_execution(EStagingStatus.FINISHED, 100, detail="Finished without processing any tasks")
            self.logger.info("There are no assets to stage. Exiting....")
            return

        # retrieve the token
        try:
            external_auth_config = load_external_auth_config_by_station_service(self.provider.lower())
            token = get_station_token(external_auth_config)
        except HTTPException as http_exception:
            self.logger.error(
                f"Failed to retrieve the token needed to connect to the external station: {http_exception}",
            )
            self.log_job_execution(
                EStagingStatus.FAILED,
                0,
                detail="Failed to retrieve the token needed to connect to the external "
                f"station {self.provider.lower()}",
            )
            return

        # connect to the dask cluster
        try:

            dask_client = self.dask_cluster_connect()
            self.submit_tasks_to_dask_cluster(token, external_auth_config.trusted_domains, dask_client)
        except RuntimeError as re:
            self.log_job_execution(EStagingStatus.FAILED, 0, detail=f"{re}")
            self.logger.error("Failed to start the staging process")
            return

        # Set the status to IN_PROGRESS for the job
        self.log_job_execution(EStagingStatus.IN_PROGRESS, 0, detail="Sending tasks to the dask cluster")

        # starting another thread for managing the dask callbacks
        self.logger.debug("Starting tasks monitoring thread")
        try:
            await asyncio.to_thread(self.manage_dask_tasks_results, dask_client)
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.debug(f"Error from tasks monitoring thread: {e}")
            self.log_job_execution(EStagingStatus.FAILED, 0, detail=f"Error from tasks monitoring thread: {e}")

        # cleanup by disconnecting the dask client
        self.assets_info = []
        dask_client.close()

    def publish_rspy_feature(self, feature: Feature):
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
            - Logs the job status as `EStagingStatus.FAILED` if the feature publishing fails.
            - Calls `self.delete_files_from_bucket()` to clean up related files in case of failure.
        """
        # Publish feature to catalog
        # how to get user? // Do we need user? should /catalog/collection/collectionId/items works with apik?
        publish_url = f"{self.catalog_url}/catalog/collections/{self.catalog_collection}/items"
        # Iterate over assets, and remove alternate field, if they already have one defined.
        for asset in feature.assets.values():
            if hasattr(asset, "alternate"):
                del asset.alternate  # type: ignore
        try:
            response = requests.post(
                publish_url,
                headers={"cookie": self.headers.get("cookie", None)},
                data=feature.json(),
                timeout=10,
            )
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
            return False

    def unpublish_rspy_features(self, feature_ids: list[str]):
        """Deletes specified features from the RSPy catalog by sending DELETE requests to the
        catalog API endpoint for each feature ID.

        This method iterates over a list of feature IDs, constructs the API URL to delete each feature,
        and sends an HTTP DELETE request to the corresponding endpoint. If the DELETE request
        fails due to HTTP errors, timeouts, or connection issues, it logs the error with appropriate details.

        Args:
            feature_ids (list): A list of feature IDs to be deleted from the RSPy catalog.

        Raises:
            requests.exceptions.HTTPError: If the server responds with an HTTP error code (4xx or 5xx).
            requests.exceptions.Timeout: If the DELETE request times out.
            requests.exceptions.RequestException: For general request-related errors.
            requests.exceptions.ConnectionError: If there is a network-related error.
            json.JSONDecodeError: If an invalid response body is encountered when attempting to decode.

        Behavior:
        1. **Request Construction**:
            - For each `feature_id` in the list, the method constructs the DELETE request URL using the
            base catalog URL, the collection name, and the feature ID.
            - The request includes a `cookie` header obtained from `self.headers`.

        2. **Error Handling**:
            - The method handles the following exceptions:
                - `HTTPError`: Raised if the server returns a 4xx or 5xx status code.
                - `Timeout`: Raised if the DELETE request takes longer than 3 seconds.
                - `RequestException`: Raised for other request-related issues, such as invalid requests.
                - `ConnectionError`: Raised when there is a connection issue (e.g., network failure).
                - `JSONDecodeError`: Raised when there is an issue decoding the response body (if expected).
            - For each error encountered, an appropriate message is logged with the exception details.

        3. **Logging**:
            - Success and failure events are logged, allowing tracing of which feature deletions
            were successful or failed, along with the relevant error information.
        """
        try:
            for feature_id in feature_ids:
                catalog_delete_item = (
                    f"{self.catalog_url}/catalog/collections/{self.catalog_collection}/items/{feature_id}"
                )
                response = requests.delete(
                    catalog_delete_item,
                    headers={"cookie": self.headers.get("cookie", None)},
                    timeout=3,
                )
                response.raise_for_status()  # Raise an error for HTTP error responses
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            json.JSONDecodeError,
        ) as exc:
            self.logger.error("Error while deleting the item from rspy catalog %s", exc)

    def __repr__(self):
        """Returns a string representation of the Staging processor."""
        return "RSPY Staging OGC API Processor"


# Register the processor
processors = {"Staging": Staging}
