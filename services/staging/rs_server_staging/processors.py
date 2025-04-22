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
"""RSPY Staging processor."""

import asyncio  # for handling asynchronous tasks
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from json import JSONDecodeError
from urllib.parse import urlparse

import requests
from dask.distributed import (
    Client,
    LocalCluster,
    as_completed,
)
from dask_gateway import Gateway
from dask_gateway.auth import BasicAuth, JupyterHubAuth
from fastapi import HTTPException
from pygeoapi.process.base import BaseProcessor
from pygeoapi.process.manager.postgresql import (
    PostgreSQLManager,  # pylint: disable=C0302
)
from pygeoapi.util import JobStatus
from requests.exceptions import RequestException
from rs_server_common import settings as common_settings
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.authentication.authentication_to_external import (
    ExternalAuthenticationConfig,
    ServiceNotFound,
    load_external_auth_config_by_domain,
)
from rs_server_common.authentication.token_auth import (
    TokenAuth,
    TokenDataNotFound,
    get_station_token,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3_MAX_RETRIES,
    S3_RETRY_TIMEOUT,
    S3StorageHandler,
)
from rs_server_common.settings import LOCAL_MODE
from rs_server_common.utils.logging import Logging
from starlette.requests import Request

from .rspy_models import Feature, FeatureCollectionModel


def streaming_task(  # pylint: disable=R0913, R0917
    product_url: str,
    s3_file: str,
    config: ExternalAuthenticationConfig,
    bucket: str,
    auth: str,
):
    """
    Streams a file from a product URL and uploads it to an S3-compatible storage.

    This function downloads a file from the specified `product_url` using provided
    authentication and uploads it to an S3 bucket using a streaming mechanism.
    If no S3 handler is provided, it initializes a default `S3StorageHandler` using
    environment variables for credentials.

    Args:
        product_url (str): The URL of the product to download.
        config (ExternalAuthenticationConfig): Authentification configuration containing the list of
        bucket (str): Name of the destination bucket where we want to stage our data
        s3_file (str): The destination path/key in the S3 bucket where the file will be uploaded.
        auth: The station token. This has to be refreshed from the caller
    Returns:
        str: The S3 file path where the file was uploaded.

    Raises:
        ValueError: If the streaming process fails, raises a ValueError with details of the failure.

    Retry Mechanism:
        - Retries occur for network-related errors (`RequestException`) or S3 client errors
        (`ClientError`, `BotoCoreError`).
        - The function waits before retrying, with the delay time increasing exponentially
        (based on the `backoff_factor`).
        - The backoff formula is `backoff_factor * (2 ** (attempt - 1))`, allowing progressively
        longer wait times between retries.
    """

    logger_dask = logging.getLogger(__name__)
    logger_dask.info("The streaming task started")
    # time.sleep(5)
    # get the retry timeout
    s3_retry_timeout = int(os.environ.get("S3_RETRY_TIMEOUT", S3_RETRY_TIMEOUT))
    # get the number of retries in case of failure
    max_retries = int(os.environ.get("S3_MAX_RETRIES", S3_MAX_RETRIES))
    # set counter for retries
    attempt = 0
    while attempt < max_retries:
        try:
            logger_dask.debug(f"{s3_file}: Creating the s3_handler")
            s3_handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            )

            s3_handler.s3_streaming_upload(product_url, config.trusted_domains, auth, bucket, s3_file)
            s3_handler.disconnect_s3()
            break
        except ConnectionError as e:
            attempt += 1
            if attempt < max_retries:
                # keep retrying
                s3_handler.disconnect_s3()
                logger_dask.error(f"S3 level failed to stream. Retrying in {s3_retry_timeout} seconds.")
                s3_handler.wait_timeout(s3_retry_timeout)
                continue
            logger_dask.exception(f"S3 level failed to stream. Tried for {max_retries} times, giving up")
            raise ValueError(
                f"Dask task failed to stream file from {product_url} to s3://{bucket}/{s3_file}. Reason: {e}",
            ) from e
        except KeyError as key_exc:
            logger_dask.exception(f"KeyError exception in streaming_task for {s3_file}: {key_exc}")
            raise ValueError(f"Cannot create s3 connector object. Reason: {key_exc}") from key_exc
        except RuntimeError as e:
            logger_dask.exception(f"RuntimeError exception in streaming_task for {s3_file} : {e}")
            raise ValueError(
                f"Dask task failed to stream file from {product_url} to s3://{bucket}/{s3_file}. Reason: {e}",
            ) from e
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger_dask.exception(f"Unhandled exception in streaming_task for {s3_file} : {e}")
            raise ValueError(
                f"Unhandled exception in streaming_task : {e}",
            ) from e
    logger_dask.info(f"The streaming task finished. Returning name of the streamed file {s3_file}")
    return s3_file


class RefreshTokenData:  # pylint: disable=too-few-public-methods
    """
    Stores and manages authentication token refresh data for an external station.

    This class maintains authentication configuration details, a token dictionary,
    and a subscriber count to track whether the token should be refreshed.

    Attributes:
        config (ExternalAuthenticationConfig): Authentication configuration for the station.
        padlock (threading.Lock): Lock to synchronize token updates.
        token_dict (dict): Dictionary containing authentication token details.
        subscribers (int): Number of active subscribers tracking the token refresh status.
    """

    def __init__(
        self,
        config: ExternalAuthenticationConfig,
    ):
        """
        Initializes the `RefreshTokenData` instance with station authentication details.

        Args:
            config (ExternalAuthenticationConfig): The authentication configuration for the station.
        """
        # NOTE: station_id has to be unique !
        self.config = config
        self.padlock = threading.Lock()
        self.token_dict: dict = {}
        self.subscribers = 1

    def station_id(self):
        """
        Retrieves the unique station identifier.

        Returns:
            str: The station ID.
        """
        return self.config.station_id

    def subscribe(self, logger):
        """
        Increments the subscriber count for token tracking.

        This method is thread-safe using a lock.

        Args:
            logger (logging.Logger): Logger instance for logging subscription events.
        """
        with self.padlock:
            self.subscribers += 1
            logger.debug(f"Subscribe to {self.station_id()}. Number of subscribers : {self.subscribers}")

    def unsubscribe(self, logger):
        """
        Decrements the subscriber count when a subscription ends.

        This method is thread-safe using a lock.

        Args:
            logger (logging.Logger): Logger instance for logging unsubscription events.
        """
        with self.padlock:
            self.subscribers -= 1
            logger.debug(f"Unsubscribe from station {self.station_id()}. Number of subscribers : {self.subscribers}")

    def update_dict_token(self, new_dict_token, logger):
        """
        Updates the authentication token dictionary with new token data.

        This method is NOT thread-safe ! The caller should use the padlock

        Args:
            new_dict_token (dict): The new token data to store.
            logger (logging.Logger): Logger instance for logging token update events.
        """
        logger.debug(f"Updating dictionary token with: {new_dict_token}")
        self.token_dict = new_dict_token.copy()

    def get_access_token(self):
        """
        Gets the access_token field from the dictionays

        This method is thread-safe using a lock.

        """
        with self.padlock:
            return self.token_dict["access_token"]


def update_station_token(auth_refresh_token: RefreshTokenData, logger: logging.Logger):
    """
    Refreshes the authentication token for an external station.

    This function retrieves the current authentication token from the shared variable,
    and refreshes it if necessary.

    Args:
        auth_refresh_token (RefreshTokenData): The authentication token data, with the dictionary that keeps the
            token.
        logger (logging.Logger): Logger instance for logging events.

    Returns:
        bool: `True` if the token was successfully refreshed, `False` if an error occurred.

    Raises:
        RuntimeError: If an unexpected error occurs during token retrieval or update.
    """
    try:
        if auth_refresh_token.subscribers == 0:
            logger.debug(f"No subscribers for {auth_refresh_token.station_id()}, so no token refreshment")
            return True
        logger.debug(f"Refreshing token for {auth_refresh_token.station_id()}")
        # Get/refresh the access token if necessary
        with auth_refresh_token.padlock:
            token_dict = get_station_token(auth_refresh_token.config, auth_refresh_token.token_dict)
            if auth_refresh_token.token_dict != token_dict:
                auth_refresh_token.update_dict_token(token_dict, logger)
    except (TokenDataNotFound, ValueError) as e:
        logger.exception(f"Token dictionary not valid: {e}")
        return False
    except HTTPException as http_exception:
        logger.exception(
            f"Failed to retrieve the token needed to connect to the external station: {http_exception}",
        )
        return False

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception(f"Unhandled exception in update_station_token: {e}")
        return False
    logger.debug("Refreshing token finished.")
    return True


class Staging(
    BaseProcessor,
):  # (metaclass=MethodWrapperMeta): - meta for stopping actions if status is failed # pylint: disable=R0913, R0902
    """
    RSPY staging implementation, the processor should perform the following actions after being triggered:

    • First, the RSPY catalog is searched to determine if some or all of the input features have already been staged.

    • If all features are already staged, the process should return immediately.

    • If there are features that haven’t been staged, the processor connects to a specified Dask cluster as a client.

    • Once connected, the processor begins asynchronously streaming each feature directly into the
    rs-dev-cluster-catalog bucket using a Dask-distributed process.

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
        request: Request,
        db_process_manager: PostgreSQLManager,
        cluster: LocalCluster,
        station_token_list: list[RefreshTokenData],
        station_token_list_lock: threading.Lock,
    ):  # pylint: disable=super-init-not-called
        """
        Initialize the Staging processor with credentials, input collection, catalog details,
        database, and cluster configuration.

        Args:
            request (Headers): original HTTP request.
            db_process_manager (PostgreSQLManager): The pygeoapi Postgresql Manager used to track job execution
                status and metadata.
            cluster (LocalCluster): The Dask LocalCluster instance used to manage distributed computation tasks.

        Attributes:
            auth_headers (dict): authentication headers from the original HTTP request.
            stream_list (list): A list to hold streaming information for processing.
            catalog_url (str): URL of the catalog service, fetched from environment or default value.
            download_url (str): URL of the RS server, fetched from environment or default value.
            job_id (str): A unique identifier for the processing job, generated using UUID.
            message (str): Status message describing the current state of the processing unit.
            progress (int): Integer tracking the progress of the current job.
            catalog_item_name (str): Name of the specific item in the catalog being processed.
            assets_info (list): Holds information about assets associated with the processing. Dask tasks are
                created from this
            logger (Logger): Logger instance for capturing log output.
            cluster (LocalCluster): Dask LocalCluster instance managing computation resources, used in local mode
                If this is None, it means we are in cluster mode, and we should dynamically connect
                to the Dask cluster for each job.
        """
        #################
        # Locals
        self.logger = Logging.default(__name__)
        self.request = request
        self.stream_list: list[Feature] = []
        #################
        # Copy authentication headers from original HTTP request
        self.auth_headers: dict[str, str] = {}
        for key in APIKEY_HEADER, "cookie", "host":
            if value := self.request.headers.get(key):
                self.auth_headers[key] = value
        #################
        # Env section
        # Set a list containing all possibles server url
        self.server_url = [
            os.getenv("RSPY_HOST_CADIP", "http://127.0.0.1:8002"),
            os.getenv("RSPY_HOST_ADGS", "http://127.0.0.1:8001"),
        ]

        self.catalog_url: str = os.environ.get(
            "RSPY_HOST_CATALOG",
            "http://127.0.0.1:8003",
        )  # get catalog href, loopback else
        #################
        # Database section
        self.job_id: str = str(uuid.uuid4())  # Generate a unique job ID
        self.message: str = "Processing Unit was created"
        self.progress: float = 0.0
        self.db_process_manager = db_process_manager
        self.status = JobStatus.accepted
        self.create_job_execution()
        #################
        # Inputs section
        self.assets_info: list = []

        self.cluster = cluster
        self.catalog_bucket = os.environ["RSPY_CATALOG_BUCKET"]
        self.station_token_list = station_token_list
        self.station_token_list_lock = station_token_list_lock

    # Override from BaseProcessor, execute is async in RSPYProcessor
    async def execute(  # pylint: disable=too-many-return-statements
        self,
        data: dict,
    ) -> tuple[str, dict]:
        """
        Asynchronously execute the RSPY staging process, starting with a catalog check and
        proceeding to feature processing if the check succeeds.

        This method first logs the creation of a new job execution and verifies the connection to
        the catalog service. If the catalog connection fails, it logs an error and stops further
        execution. If the connection is successful, it initiates the asynchronous processing of
        RSPY features.

        If the current event loop is running, the feature processing task is scheduled asynchronously.
        Otherwise, the event loop runs until the processing task is complete.

        Args:
            data (dict): input data that the process needs in order to execute

        Returns:
            tuple: tuple of MIME type and process response (dictionary containing the job ID and a
                status message).
                Example: ("application/json", {"running": <job_id>})

        Logs:
            Error: Logs an error if connecting to the catalog service fails.

        Raises:
            None: This method doesn't raise any exceptions directly but logs errors if the
                catalog check fails.
        """
        # If the content of the staging body is a link STAC itemCollection
        # (and has no 'value' field containing a STAC ItemCollection)
        # we launch a request to the corresponding service to load the STAC itemCollection
        try:
            if "items" in data and "href" in data["items"] and "value" not in data["items"]:

                # Check if the given url is either the cadip or the
                # auxip - we don't want to send our apikey to any url
                if not any(href in data["items"]["href"] for href in self.server_url):
                    return self.log_job_execution(
                        JobStatus.failed,
                        0,
                        "The domain name specified in the input link must correspond to an existing server",
                    )
                response = requests.get(
                    data["items"]["href"],
                    headers=self.auth_headers,
                    timeout=5,
                )
                response.raise_for_status()
                response_dict = response.json()
                if "type" not in response_dict or response_dict["type"] != "FeatureCollection":
                    raise RequestException(
                        f"The input link must point to a FeatureCollection: invalid response {response_dict}",
                    )

                data["items"]["value"] = response_dict
        except (RequestException, JSONDecodeError, RuntimeError) as exc:
            return self.log_job_execution(
                JobStatus.failed,
                0,
                f"Failed to retrieve the ItemCollection from the input link: {exc}",
            )

        # self.logger.debug(f"Executing staging processor for {data}")
        item_collection: FeatureCollectionModel | None = (
            FeatureCollectionModel.parse_obj(data["items"]["value"])
            if "items" in data and "value" in data["items"]
            else None
        )
        catalog_collection: str = data["collection"]

        # Check for the proper input
        # Check if item collection is provided
        if not item_collection or not hasattr(item_collection, "features"):
            return self.log_job_execution(
                JobStatus.successful,
                0,
                "No valid items were provided in the input for staging",
            )
        # Handle the case where we have an empty ItemCollection
        if len(item_collection.features) == 0:
            return self.log_job_execution(JobStatus.successful, 100, "Finished without processing any tasks")

        # Filter out features with no assets
        item_collection.features = [feature for feature in item_collection.features if feature.assets]

        # Check if any features with assets remain
        if not item_collection.features:
            return self.log_job_execution(
                JobStatus.successful,
                0,
                "No items with assets were found in the input for staging",
            )

        # Execution section
        if not await self.check_catalog(catalog_collection, item_collection.features):
            return self.log_job_execution(
                JobStatus.failed,
                0,
                f"Failed to start the staging process. Checking the collection '{catalog_collection}' failed !",
            )
        self.log_job_execution(JobStatus.running, 0, "Successfully searched catalog")
        # Start execution
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If the loop is running, schedule the async function
            asyncio.create_task(self.process_rspy_features(catalog_collection))
        else:
            # If the loop is not running, run it until complete
            loop.run_until_complete(self.process_rspy_features(catalog_collection))

        return self._get_execute_result()

    def _get_execute_result(self) -> tuple[str, dict]:
        return "application/json", {self.status.value: self.job_id}

    def create_job_execution(self):
        """
        Creates a new job execution entry and tracks its status.

        This method creates a job entry in the tracker with the current job's ID, status,
        progress, and message. The job information is stored in a persistent tracker to allow
        monitoring and updating of the job's execution state.

        The following information is stored:
            - `job_id`: The unique identifier for the job.
            - `status`: The current status of the job, converted to a JSON-serializable format.
            - `progress`: The progress of the job execution.
            - `message`: Additional details about the job's execution.

        Notes:
            - The `self.tracker` is expected to have an `insert` method to store the job information.
            - The status is converted to JSON using `JobStatus.to_json()`.

        """
        job_metadata = {
            "identifier": self.job_id,
            "processID": "staging",
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
        }
        self.db_process_manager.add_job(job_metadata)

    def log_job_execution(
        self,
        status: JobStatus | None = None,
        progress: int | None = None,
        message: str | None = None,
    ) -> tuple[str, dict]:
        """
        Method used to log progress into db.

        Args:
            status (JobStatus): new job status
            progress (int): new job progress (percentage)
            message (str): new job current information message

        Returns:
            tuple: tuple of MIME type and process response (dictionary containing the job ID and a
                status message).
                Example: ("application/json", {"running": <job_id>})
        """
        # Update both runtime and db status and progress

        self.status = status if status else self.status
        self.progress = progress if progress else self.progress
        self.message = message if message else self.message

        update_data = {
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "updated": datetime.now(),  # Update updated each time a change is made
        }
        if status == JobStatus.failed:
            self.logger.error(f"Updating failed job {self.job_id}: {update_data}")
        else:
            self.logger.info(f"Updating job {self.job_id}: {update_data}")

        self.db_process_manager.update_job(self.job_id, update_data)
        return self._get_execute_result()

    async def check_catalog(self, catalog_collection: str, features: list[Feature]) -> bool:
        """
        Method used to check RSPY catalog if a feature from input_collection is already published.

        Args:
            catalog_collection (str): Name of the catalog collection.
            features (list): list of features to process.

        Returns:
            bool: True in case of success, False otherwise
        """
        # Set the filter containing the item ids to be inserted
        # Get each feature id and create /catalog/search argument
        ids = [f"'{feature.id}'" for feature in features]
        filter_object = {
            "collections": catalog_collection,
            "filter-lang": "cql2-text",
            "filter": f"id IN ({', '.join(ids)})",
            "limit": str(len(ids)),
        }

        search_url = f"{self.catalog_url}/catalog/search"

        try:
            response = requests.get(
                search_url,
                headers=self.auth_headers,
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
            self.create_streaming_list(features, item_collection)
            return True
        except (RequestException, JSONDecodeError, RuntimeError) as exc:
            self.log_job_execution(JobStatus.failed, 0, f"Failed to search catalog: {exc}")
            return False

    def create_streaming_list(self, features: list[Feature], catalog_response: dict):
        """
        Prepares a list of items for download based on the catalog response.

        This method compares the features in the provided `catalog_response` with the features
        already present in `features`. If all features have been returned
        in the catalog response, the streaming list is cleared. Otherwise, it determines which
        items are not yet downloaded and updates `self.stream_list` with those items.

        Args:
            features (list): The list of features to process.
            catalog_response (dict): A dictionary response from a catalog search.

        Behavior:
            - If the number of items in `catalog_response["context"]["returned"]` matches the
            total number of items in `features`, `self.stream_list`
            is set to an empty list, indicating that there are no new items to download.
            - If the `catalog_response["features"]` is empty (i.e., no items were found in the search),
            it assumes no items have been downloaded and sets `self.stream_list` to all features
            in `features`.
            - Otherwise, it computes the difference between the items in `features`
            and the items already listed in the catalog response, updating `self.stream_list` to
            contain only those that have not been downloaded yet.

        Side Effects:
            - Updates `self.stream_list` with the features that still need to be downloaded.

        """
        # Based on catalog response, pop out features already in catalog and prepare rest for download
        try:
            if not catalog_response["features"]:
                # No search result found, process everything from item_collection
                self.stream_list = features
            else:
                # Do the difference, call rs-server-download only with features to be downloaded
                # Extract IDs from the catalog response directly
                already_downloaded_ids = {feature["id"] for feature in catalog_response["features"]}
                # Select only features whose IDs have not already been downloaded (returned in /search)
                not_downloaded_features = [item for item in features if item.id not in already_downloaded_ids]
                self.stream_list = not_downloaded_features
        except KeyError as ke:
            self.logger.exception(
                f"The 'features' field is missing in the response from the catalog service. {ke}",
            )

            raise RuntimeError(
                "The 'features' field is missing in the response from the catalog service.",
            ) from ke

    def prepare_streaming_tasks(self, catalog_collection: str, feature: Feature):
        """Prepare tasks for the given feature to the Dask cluster.

        Args:
            catalog_collection (str): Name of the catalog collection.
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
            s3_obj_path = f"{catalog_collection}/{feature.id.rstrip('/')}/{asset_name}"
            self.assets_info.append((asset_content.href, s3_obj_path))
            # update the s3 path, this will be checked in the rs-server-catalog in the
            # publishing phase
            asset_content.href = f"s3://rtmpop/{s3_obj_path}"
            feature.assets[asset_name] = asset_content
        return True

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

    def wait_for_dask_completion(self, client: Client):
        """Waits for all Dask tasks to finish before proceeding."""
        timeout = int(os.environ.get("RSPY_STAGING_TIMEOUT", 600))
        while timeout > 0:
            if not client.call_stack():
                break  # No tasks running anymore
            time.sleep(1)
            timeout -= 1

    def publish_processed_features(self, catalog_collection: str, refresh_token: RefreshTokenData) -> bool:
        """Handles publishing features and cleanup in case of failure."""
        # Publish all the features once processed
        published_featurs_ids: list[str] = []
        for feature in self.stream_list:
            if not self.publish_rspy_feature(catalog_collection, feature):
                # cleanup
                self.log_job_execution(
                    JobStatus.failed,
                    None,
                    f"The item {feature.id} couldn't be published in the catalog. Cleaning up",
                )

                # delete the files
                self.delete_files_from_bucket()
                # delete the published items
                self.unpublish_rspy_features(catalog_collection, published_featurs_ids)
                refresh_token.unsubscribe(self.logger)
                self.logger.error(f"The item {feature.id} couldn't be published in the catalog")
                return False
            published_featurs_ids.append(feature.id)
        return True

    def manage_dask_tasks(self, client: Client, catalog_collection: str, refresh_token: RefreshTokenData):
        """
        Manages Dask tasks for streaming data to the RS-Server.

        This method monitors Dask tasks dynamically, updating the job execution status in the database
        as tasks progress. If any task fails, the following actions occur:
            - The remaining tasks are canceled.
            - The system waits for running tasks to finish (up to `RSPY_STAGING_TIMEOUT` or 600 seconds).
            - All streamed files in the S3 bucket are deleted.
            - The job execution status is marked as failed.

        If all tasks complete successfully, the processed features are
        published, and job execution is marked as successful.

        Args:
            client (Client): The Dask client managing task execution.
            catalog_collection (str): The catalog collection name for storing processed features.
            refresh_token (RefreshTokenData): The authentication data, including the station access token.

        Raises:
            RuntimeError: If a failure occurs while submitting tasks, retrieving tokens,
                        or processing tasks within the Dask cluster.
        """
        self.logger.info("Tasks monitoring started")
        if not client:
            self.logger.error("The dask cluster client object is not created. Exiting")
            self.log_job_execution(
                JobStatus.failed,
                None,
                "Submitting task to dask cluster failed. Dask cluster client object is not created",
            )
            refresh_token.unsubscribe(self.logger)
            return

        # prevent submitting more tasks than necessary.
        # this can occur when the number of tasks that can run in parallel
        # exceeds the actual number of tasks intended for submission.
        max_parallel_tasks = min(sum(client.nthreads().values()), len(self.assets_info))
        self.logger.info(f"Number of tasks asigned to the initial batch: {max_parallel_tasks}")
        # convert to iterator for dynamic updates
        data_iter = iter(self.assets_info)
        try:
            # if "access_token" not in refresh_token.token_dict will raise a KeyError and
            # caught by Exception
            # the access_token dictionary was refreshed just before starting
            # this thread. no need to do it for the initial batch
            access_token = TokenAuth(refresh_token.get_access_token())
            # initial dataset
            initial_batch_tasks = {
                client.submit(
                    streaming_task,
                    *next(data_iter),
                    refresh_token.config,
                    self.catalog_bucket,
                    access_token,
                )
                for _ in range(max_parallel_tasks)
            }
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.exception(f"Submitting task to dask cluster failed. Reason: {e}")
            self.log_job_execution(JobStatus.failed, None, f"Submitting task to dask cluster failed. Reason: {e}")
            refresh_token.unsubscribe(self.logger)
            return
        # counter to be used for percentage
        completed_tasks = 0
        tasks = as_completed(initial_batch_tasks)
        for task in tasks:
            try:
                res = task.result()  # This will raise the exception from the task if it failed
                self.logger.debug(f"Task result = {res}")
                completed_tasks += 1
                self.log_job_execution(
                    JobStatus.running,
                    round(completed_tasks * 100 / len(self.assets_info)),
                    "In progress",
                )
                self.logger.debug("%s Task streaming completed", task.key)
                # Submit a new task if available and no errors occurred
                try:
                    new_task = next(data_iter)
                    # refresh the token if needed
                    if not update_station_token(refresh_token, self.logger):
                        raise RuntimeError("Could not retrieve or refresh the station token")
                    access_token = TokenAuth(refresh_token.get_access_token())
                    # submit the task
                    tasks.add(
                        client.submit(
                            streaming_task,
                            *new_task,
                            refresh_token.config,
                            self.catalog_bucket,
                            access_token,
                        ),
                    )

                except StopIteration:
                    pass  # No more data to process
            except Exception as task_e:  # pylint: disable=broad-exception-caught
                self.logger.error("Task failed with exception: %s", task_e)
                client.cancel(tasks)
                # Wait for all the current running tasks to complete.
                self.wait_for_dask_completion(client)
                # Update status for the job
                self.log_job_execution(JobStatus.failed, None, f"At least one of the tasks failed: {task_e}")
                self.delete_files_from_bucket()
                refresh_token.unsubscribe(self.logger)
                self.logger.error(f"Tasks monitoring finished with error. At least one of the tasks failed: {task_e}")
                return

        if not self.publish_processed_features(catalog_collection, refresh_token):
            return

        # Update status once all features are processed
        self.log_job_execution(JobStatus.successful, 100, "Finished")
        # Update the subscribers for token refreshment
        refresh_token.unsubscribe(self.logger)
        self.logger.info("Tasks monitoring finished")

    def dask_cluster_connect(
        self,
    ):  # pylint: disable=too-many-branches, too-many-statements, too-many-locals
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
            Dask client
        """

        # If self.cluster is already initialized, it means the application is running in local mode, and
        # the cluster was created when the application started.
        if not self.cluster:
            # Connect to the gateway and get the list of the clusters
            try:
                # get the name of the cluster
                cluster_name = os.environ["RSPY_DASK_STAGING_CLUSTER_NAME"]
                # In local mode, authenticate to the dask cluster with username/password
                if common_settings.LOCAL_MODE:
                    gateway_auth = BasicAuth(
                        os.environ["LOCAL_DASK_USERNAME"],
                        os.environ["LOCAL_DASK_PASSWORD"],
                    )

                # Cluster mode
                else:
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

                # Sort the clusters by newest first
                clusters = sorted(gateway.list_clusters(), key=lambda cluster: cluster.start_time, reverse=True)
                self.logger.debug(f"Cluster list for gateway {os.environ['DASK_GATEWAY__ADDRESS']!r}: {clusters}")

                # In local mode, get the first cluster from the gateway.
                cluster_id = None
                if common_settings.LOCAL_MODE:
                    if clusters:
                        cluster_id = clusters[0].name

                # In cluster mode, get the identifier of the cluster whose name is equal to the cluster_name variable.
                # Protection for the case when this cluster does not exit
                else:
                    self.logger.info(f"my cluster name: {cluster_name}")

                    for cluster in clusters:
                        self.logger.info(f"Existing cluster names: {cluster.options.get('cluster_name')}")

                        is_equal = cluster.options.get("cluster_name") == cluster_name
                        self.logger.info(f"Is equal: {is_equal}")

                    cluster_id = next(
                        (
                            cluster.name
                            for cluster in clusters
                            if isinstance(cluster.options, dict) and cluster.options.get("cluster_name") == cluster_name
                        ),
                        None,
                    )
                    self.logger.info(f"Cluster id vaut: {cluster_id}")

                if not cluster_id:
                    raise IndexError(f"Dask cluster with 'cluster_name'={cluster_name!r} was not found.")

                self.cluster = gateway.connect(cluster_id)
                self.logger.info(f"Successfully connected to the {cluster_name} dask cluster")

            except KeyError as e:
                self.logger.exception(
                    "Failed to retrieve the required connection details for "
                    "the Dask Gateway from one or more of the following environment variables: "
                    "DASK_GATEWAY__ADDRESS, RSPY_DASK_STAGING_CLUSTER_NAME, "
                    f"JUPYTERHUB_API_TOKEN, DASK_GATEWAY__AUTH__TYPE. {e}",
                )

                raise RuntimeError(
                    f"Failed to retrieve the required connection details for Dask Gateway. Missing key:{e}",
                ) from e
            except IndexError as e:
                self.logger.exception(f"Failed to find the specified dask cluster: {e}")
                raise RuntimeError(f"No dask cluster named '{cluster_name}' was found.") from e

        self.logger.debug("Cluster dashboard: %s", self.cluster.dashboard_link)
        # create the client as well
        client = Client(self.cluster)

        # Forward logging from dask workers to the caller
        client.forward_logging()

        def set_dask_env(host_env: dict):
            """Pass environment variables to the dask workers."""
            for name in ["S3_ACCESSKEY", "S3_SECRETKEY", "S3_ENDPOINT", "S3_REGION"]:
                os.environ[name] = host_env[name]

            # Some kind of workaround for boto3 to avoid checksum being added inside
            # the file contents uploaded to the s3 bucket e.g. x-amz-checksum-crc32:xxx
            # See: https://github.com/boto/boto3/issues/4435
            os.environ["AWS_REQUEST_CHECKSUM_CALCULATION"] = "when_required"
            os.environ["AWS_RESPONSE_CHECKSUM_VALIDATION"] = "when_required"

        client.run(set_dask_env, os.environ)

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

    def get_refresh_token(self, domain) -> RefreshTokenData:
        """Handles authentication token retrieval and refresh."""
        try:
            external_auth_config = load_external_auth_config_by_domain(domain)
            if not external_auth_config:
                raise HTTPException(
                    status_code=401,
                    detail="Failed to retrieve the configuration for the station token.",
                )
            if not LOCAL_MODE:
                from rs_server_common.authentication.authentication import (  # pylint: disable=import-outside-toplevel
                    auth_validation,
                )

                auth_validation(
                    external_auth_config.station_id,
                    "staging_download",
                    request=self.request,
                    staging_process=True,
                )

        except (ServiceNotFound, HTTPException) as e:
            self.logger.exception(f"{e}")
            raise RuntimeError(f"{e}") from e

        # Find or create a token
        with self.station_token_list_lock:
            for refresh_token in self.station_token_list:
                if refresh_token.station_id() == external_auth_config.station_id:
                    refresh_token.subscribe(self.logger)
                    break
            else:
                refresh_token = RefreshTokenData(external_auth_config)
                self.station_token_list.append(refresh_token)

        if not update_station_token(refresh_token, self.logger):
            refresh_token.unsubscribe(self.logger)
            self.logger.error("Could not retrieve or refresh the station token.")
            raise RuntimeError("Could not retrieve or refresh the station token.")

        return refresh_token

    async def process_rspy_features(  # pylint: disable=too-many-return-statements
        self,
        catalog_collection: str,
    ) -> tuple[str, dict]:
        """
        Method used to trigger dask distributed streaming process.
        It creates dask client object, gets the external data sources access token
        Prepares the tasks for execution
        Manage eventual runtime exceptions

        Args:
            catalog_collection (str): Name of the catalog collection.

        Returns:
            tuple: tuple of MIME type and process response (dictionary containing the job ID and a
                status message).
                Example: ("application/json", {"running": <job_id>})
        """
        self.logger.debug("Starting main loop")

        # Step 1: Validate and prepare streaming tasks
        # Process each feature by initiating the streaming download of its assets to the final bucket.
        for feature in self.stream_list:
            if not self.prepare_streaming_tasks(catalog_collection, feature):
                return self.log_job_execution(JobStatus.failed, 0, "Unable to create tasks for the Dask cluster")

        if not self.assets_info:
            self.logger.info("There are no assets to stage. Exiting....")
            return self.log_job_execution(JobStatus.successful, 100, "Finished without processing any tasks")

        # Step 2: Determine the domain and validate it, currently unable to stage from multiple domains
        domains = list({urlparse(asset[0]).hostname for asset in self.assets_info})
        self.logger.info(f"Staging from domain(s) {domains}")
        if len(domains) > 1:
            return self.log_job_execution(JobStatus.failed, 0, "Staging from multiple domains is not supported yet")
        domain = domains[0]

        # Step 3: Connect to dask cluster BEFORE retrieving the token, because an unnecessary request would be sent
        # to the external station if the connection to the dask cluster fails
        try:
            dask_client = self.dask_cluster_connect()
        except RuntimeError as re:
            self.logger.error("Failed to start the staging process")
            return self.log_job_execution(JobStatus.failed, 0, str(re))

        # Step 4: Retrieve the authentication token (only if dask connection succeeded)
        try:
            refresh_token = self.get_refresh_token(domain)
            self.log_job_execution(JobStatus.running, 0, "Sending tasks to the dask cluster")
        except RuntimeError as re:
            self.logger.error("Failed to start the staging process")
            return self.log_job_execution(JobStatus.failed, 0, f"Loading station token service failed: {re}")

        # Step 5: Manage dask tasks in a separate thread
        # starting a thread for managing the dask callbacks
        self.logger.debug("Starting tasks monitoring thread")
        try:
            await asyncio.to_thread(
                self.manage_dask_tasks,
                dask_client,
                catalog_collection,
                refresh_token,
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.log_job_execution(JobStatus.failed, 0, f"Error from tasks monitoring thread: {e}")

        # cleanup by disconnecting the dask client
        self.assets_info = []
        dask_client.close()

        return self._get_execute_result()

    def publish_rspy_feature(self, catalog_collection: str, feature: Feature):
        """
        Publishes a given feature to the RSPY catalog.

        This method sends a POST request to the catalog API to publish a feature (in the form
        of a dictionary) to a specified collection. The feature is serialized into JSON format
        and published to the `/catalog/collections/{collectionId}/items` endpoint.

        Args:
            catalog_collection (str): Name of the catalog collection.
            feature (dict): The feature to be published, represented as a dictionary. It should
            include all necessary attributes required by the catalog.

        Returns:
            bool: Returns `True` if the feature was successfully published, otherwise returns `False`
            in case of an error.

        Raises:
            None directly (all exceptions are caught and logged).

        Logging:
            - Logs an error message with details if the request fails.
            - Logs the job status as `JobStatus.failed` if the feature publishing fails.
            - Calls `self.delete_files_from_bucket()` to clean up related files in case of failure.
        """
        # Publish feature to catalog
        # how to get user? // Do we need user? should /catalog/collection/collectionId/items works with apik?
        publish_url = f"{self.catalog_url}/catalog/collections/{catalog_collection}/items"
        # Iterate over assets, and remove alternate field, if they already have one defined.
        for asset in feature.assets.values():
            if hasattr(asset, "alternate"):
                del asset.alternate  # type: ignore
        try:
            response = requests.post(
                publish_url,
                headers=self.auth_headers,
                data=feature.json(),
                timeout=10,
            )
            response.raise_for_status()  # Raise an error for HTTP error responses
            return True
        except (RequestException, JSONDecodeError) as exc:
            self.logger.error("Error while publishing items to rspy catalog %s", exc)
            return False

    def unpublish_rspy_features(self, catalog_collection: str, feature_ids: list[str]):
        """Deletes specified features from the RSPy catalog by sending DELETE requests to the
        catalog API endpoint for each feature ID.

        This method iterates over a list of feature IDs, constructs the API URL to delete each feature,
        and sends an HTTP DELETE request to the corresponding endpoint. If the DELETE request
        fails due to HTTP errors, timeouts, or connection issues, it logs the error with appropriate details.

        Args:
            catalog_collection (str): Name of the catalog collection.
            feature_ids (list): A list of feature IDs to be deleted from the RSPy catalog.

        Raises:
            None directly (all exceptions are caught and logged).

        Behavior:
        1. **Request Construction**:
            - For each `feature_id` in the list, the method constructs the DELETE request URL using the
            base catalog URL, the collection name, and the feature ID.
            - The request includes a `cookie` or api key header obtained from the original HTTP request.

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
                catalog_delete_item = f"{self.catalog_url}/catalog/collections/{catalog_collection}/items/{feature_id}"
                response = requests.delete(
                    catalog_delete_item,
                    headers=self.auth_headers,
                    timeout=3,
                )
                response.raise_for_status()  # Raise an error for HTTP error responses
        except (RequestException, JSONDecodeError) as exc:
            self.logger.error("Error while deleting the item from rspy catalog %s", exc)

    def __repr__(self):
        """Returns a string representation of the Staging processor."""
        return "RSPY Staging OGC API Processor"


# Register the processor
processors = {"Staging": Staging}
