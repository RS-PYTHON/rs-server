# Copyright 2023-2026 Airbus, CS Group
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
import getpass
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from json import JSONDecodeError, dumps
from queue import Empty
from urllib.parse import urlparse

import boto3
import botocore
import requests
from dask.distributed import (
    Client,
    Future,
    LocalCluster,
)
from dask.distributed import Queue as DaskQueue
from dask.distributed import (
    as_completed,
)
from dask_gateway import Gateway
from dask_gateway.auth import BasicAuth, JupyterHubAuth
from fastapi import HTTPException
from opentelemetry.propagate import inject
from pygeoapi.process.base import BaseProcessor
from pygeoapi.process.manager.postgresql import (
    PostgreSQLManager,  # pylint: disable=C0302
)
from pygeoapi.util import JobStatus
from requests.exceptions import RequestException
from rs_server_common import settings as common_settings
from rs_server_common.authentication import authentication
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.authentication.authentication_to_external import (
    ServiceNotFound,
    load_external_auth_config_by_domain,
)
from rs_server_common.authentication.external_authentication_config import (
    ExternalAuthenticationConfig,
)
from rs_server_common.authentication.token_auth import TokenAuth
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3StorageHandler,
)
from rs_server_common.settings import LOCAL_MODE
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import S3Credentials
from rs_server_staging.processors.authentication import (
    RefreshTokenData,
    update_station_token,
)
from rs_server_staging.processors.tasks import prepare_streaming_tasks, streaming_task
from rs_server_staging.utils.asset_info import AssetInfo
from rs_server_staging.utils.rspy_models import Feature, FeatureCollectionModel
from rs_server_staging.utils.tools import get_minimal_collection_body
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)


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
            station_token_list (list[RefreshTokenData]): Shared list of refresh tokens for all stations.
            station_token_list_lock (threading.Lock): Lock protecting concurrent access to station_token_list.

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
        self.expired_items: list[Feature] = []
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
            os.getenv("RSPY_HOST_PRIP", "http://127.0.0.1:8005"),
        ]

        self.catalog_url: str = os.environ.get(
            "RSPY_HOST_CATALOG",
            "http://127.0.0.1:8003",
        )  # get catalog href, loopback else
        self.catalog_publish_timeout: int = int(os.environ.get("RSPY_CATALOG_PUBLISH_TIMEOUT", "120"))
        self.catalog_publish_max_retries: int = int(os.environ.get("RSPY_CATALOG_PUBLISH_MAX_RETRIES", "3"))
        self.catalog_publish_retry_delay: float = float(os.environ.get("RSPY_CATALOG_PUBLISH_RETRY_DELAY", "30"))
        self.staging_user: str = "staging_user"
        #################
        # Database section
        self.job_id: str = str(uuid.uuid4())  # Generate a unique job ID
        self.message: str = "Processing Unit was created"
        self.progress: int = 0
        self.db_process_manager = db_process_manager
        self.status = JobStatus.accepted
        self.create_job_execution()
        #################
        # Inputs section
        self.assets_info: list[AssetInfo] = []
        self.named_assets: bool = False
        self.cluster = cluster
        self.station_token_list = station_token_list
        self.station_token_list_lock = station_token_list_lock
        self.logger.info(
            "Created staging job %s for user %s; catalog_url=%s",
            self.job_id,
            self.staging_user,
            self.catalog_url,
        )
        self.logger.debug(
            "Staging job %s initialized with auth header keys=%s, local_cluster=%s, "
            "publish_timeout=%s, max_retries=%s",
            self.job_id,
            list(self.auth_headers.keys()),
            bool(self.cluster),
            self.catalog_publish_timeout,
            self.catalog_publish_max_retries,
        )

    def _resolve_items_from_link(self, data: dict) -> dict | tuple[str, dict] | None:
        """
        Resolve items from an external link if provided.
        Returns the resolved Feature / FeatureCollection dict or None.
        """
        try:
            items = data.get("items")
            if not items or "href" not in items or "value" in items:
                self.logger.debug("Job %s has no external item href to resolve", self.job_id)
                return None

            # Check if the given url is from us (cadip, auxip or prip)
            # we don't want to send our apikey to any url
            self.logger.info("Resolving staging input link for job %s", self.job_id)
            self.logger.debug("Job %s resolving input items href=%s", self.job_id, items["href"])
            if any(href in items["href"] for href in self.server_url):
                response = requests.get(items["href"], timeout=60, headers=self.auth_headers)
            else:
                response = requests.get(items["href"], timeout=60)
            response.raise_for_status()
            response_dict = response.json()
            self.logger.info(
                "Resolved staging input link for job %s as %s",
                self.job_id,
                response_dict.get("type"),
            )
            self.logger.debug("Resolved input payload for job %s: %s", self.job_id, response_dict)

            if response_dict.get("type") not in ("Feature", "FeatureCollection"):
                raise ValueError("The input link must point to a Feature or FeatureCollection")

            return response_dict

        except (RequestException, RuntimeError) as exc:
            self.logger.exception("Failed to resolve staging input link for job %s: %s", self.job_id, exc)
            self.log_job_execution(
                JobStatus.failed,
                0,
                f"Failed to retrieve the ItemCollection from the input link: {exc}",
            )
            return None

    def _parse_item_collection(self, item_value: dict) -> FeatureCollectionModel | None:
        """
        Convert a Feature or FeatureCollection dict into a FeatureCollectionModel.

        Staging accepts both a single STAC Feature and a FeatureCollection. A single
        Feature is wrapped in a FeatureCollection so the rest of the workflow can
        process one normalized shape.

        Args:
            item_value: Raw STAC payload coming from the execute body or a resolved href.

        Returns:
            A validated FeatureCollectionModel, or None when the payload type is unsupported.
        """
        item_type = item_value.get("type")
        self.logger.debug("Parsing staging input for job %s; item_type=%s", self.job_id, item_type)

        if item_type == "Feature":
            # Normalize single-item requests so downstream code only has to handle
            # FeatureCollectionModel.features.
            collection = FeatureCollectionModel(
                type="FeatureCollection",
                features=[Feature.model_validate(item_value)],
            )
            self.logger.info("Parsed single feature %s for staging job %s", collection.features[0].id, self.job_id)
            return collection

        if item_type == "FeatureCollection":
            collection = FeatureCollectionModel.model_validate(item_value)
            # Some tests patch model_validate with a generic Mock; keep logging defensive
            # so observability never changes the function's validation behavior.
            features = collection.features if isinstance(collection.features, list) else []
            self.logger.info("Parsed %d features for staging job %s", len(features), self.job_id)
            self.logger.debug("Parsed feature ids for job %s: %s", self.job_id, [f.id for f in features])
            return collection

        return None

    def _filter_features_with_assets(
        self,
        item_collection: FeatureCollectionModel,
        asset_names: set[str] | None = None,
    ) -> bool:
        """
        Filter features without assets and optionally keep only selected asset names.

        - If `asset_names` is None or empty, keep all features having at least one asset.
        - If `asset_names` is provided, each feature keeps only assets whose key
        is present in the set. Features with no remaining assets are removed.

        Returns False if processing should stop.
        """
        initial_count = len(item_collection.features or [])
        self.logger.debug(
            "Filtering features for job %s; initial_count=%d, requested_asset_names=%s",
            self.job_id,
            initial_count,
            sorted(asset_names) if asset_names else [],
        )
        if not item_collection.features:
            self.log_job_execution(
                JobStatus.successful,
                100,
                "Finished without processing any tasks",
            )
            return False

        if asset_names:
            for feature in item_collection.features:
                before_assets = set(feature.assets.keys())
                # `asset_names` is an optional user selection: keep the feature, but
                # narrow its assets to the requested subset before scheduling Dask tasks.
                feature.assets = {key: value for key, value in feature.assets.items() if key in asset_names}
                self.logger.debug(
                    "Filtered assets for job %s feature %s from %s to %s",
                    self.job_id,
                    feature.id,
                    sorted(before_assets),
                    sorted(feature.assets.keys()),
                )

        # Features without assets cannot produce streaming tasks; dropping them here
        # lets the job finish cleanly instead of failing later in Dask scheduling.
        item_collection.features = [feature for feature in item_collection.features if feature.assets]
        self.logger.info(
            "Prepared %d/%d features with assets for staging job %s",
            len(item_collection.features),
            initial_count,
            self.job_id,
        )
        if not item_collection.features:
            self.log_job_execution(
                JobStatus.successful,
                0,
                "No items with assets were found in the input for staging",
            )
            return False

        return True

    async def execute(  # pylint: disable=arguments-differ,invalid-overridden-method
        self,
        data: dict,
    ) -> tuple[str, dict]:
        """
        Asynchronously execute the RSPY staging process.

        The method performs the synchronous validation/preparation phase of a
        staging request: resolving linked inputs, normalizing the STAC payload,
        filtering assets, checking catalog state, and finally scheduling the
        background streaming workflow.

        Args:
            data: Validated pygeoapi execute payload.

        Returns:
            MIME type and response body containing the current job status mapped
            to the generated job id.
        """
        self.logger.info("Starting staging execution for job %s", self.job_id)
        self.logger.debug("Raw execute input for job %s: %s", self.job_id, data)
        resolved_items = self._resolve_items_from_link(data)
        if resolved_items is None and "href" in data.get("items", {}):
            self.logger.info("Stopping staging job %s after input link resolution failure", self.job_id)
            return self._get_execute_result()

        if resolved_items:
            data["items"]["value"] = resolved_items

        item_value = data.get("items", {}).get("value")
        if not item_value:
            self.logger.info("Staging job %s received no valid items", self.job_id)
            return self.log_job_execution(
                JobStatus.successful,
                0,
                "No valid items were provided in the input for staging",
            )

        item_collection = self._parse_item_collection(item_value)
        if not item_collection:
            self.logger.error("Staging job %s received invalid input type", self.job_id)
            return self.log_job_execution(
                JobStatus.failed,
                0,
                "Invalid input type: must be Feature or FeatureCollection",
            )

        catalog_collection: str = data["collection"]

        self.staging_user = getpass.getuser() if common_settings.LOCAL_MODE else self.request.state.user_login
        self.named_assets = bool(data.get("asset_names"))
        self.logger.info(
            "Staging job %s targets collection %s as user %s",
            self.job_id,
            catalog_collection,
            self.staging_user,
        )
        if not self._filter_features_with_assets(item_collection, data.get("asset_names", None)):
            return self._get_execute_result()

        self.logger.info(
            "Checking catalog state for job %s; collection=%s, feature_count=%d",
            self.job_id,
            catalog_collection,
            len(item_collection.features),
        )
        if not await self.check_catalog(catalog_collection, item_collection.features):
            return self.log_job_execution(
                JobStatus.failed,
                0,
                f"Failed to start the staging process. Checking the collection '{catalog_collection}' failed !",
            )

        self.log_job_execution(JobStatus.running, 0, "Successfully searched catalog")

        loop = asyncio.get_event_loop()
        if loop.is_running():
            self.logger.debug("Scheduling background staging task for job %s on running event loop", self.job_id)
            _ = asyncio.create_task(self.process_rspy_features(catalog_collection))
        else:
            self.logger.debug("Running staging task for job %s until completion on current event loop", self.job_id)
            loop.run_until_complete(self.process_rspy_features(catalog_collection))

        return self._get_execute_result()

    # Override from BaseProcessor, execute is async in RSPYProcessor

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
            "progress": int(self.progress),
            "message": self.message,
        }
        self.logger.debug("Creating job execution record for %s: %s", self.job_id, job_metadata)
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
            "progress": int(self.progress),
            "message": self.message,
            "updated": datetime.now(),  # Update updated each time a change is made
        }
        if status == JobStatus.failed:
            self.logger.error(f"Updating failed job {self.job_id}: {update_data}")
        else:
            self.logger.info(f"Updating job {self.job_id}: {update_data}")

        self.db_process_manager.update_job(self.job_id, update_data)
        return self._get_execute_result()

    def check_if_collection_exists(self, catalog_collection):
        """
        Checks if a catalog collection exists in the remote catalog service.
        If the collection does not exist (HTTP 404), attempts to create it.

        Args:
            catalog_collection (str): The identifier of the catalog collection to check or create.

        Returns:
            bool: True if the collection exists or was successfully created; False otherwise.
        """
        collection_url = f"{self.catalog_url}/catalog/collections/{catalog_collection}"
        self.logger.info("Checking catalog collection %s for job %s", catalog_collection, self.job_id)
        self.logger.debug("Catalog collection check URL for job %s: %s", self.job_id, collection_url)

        try:
            # Check if collection exists in catalog
            response = requests.get(collection_url, headers=self.auth_headers, timeout=5)
            self.logger.debug(
                "Catalog collection check response for job %s collection %s: status=%s",
                self.job_id,
                catalog_collection,
                response.status_code,
            )

            if response.status_code == HTTP_200_OK:
                self.logger.info("Catalog collection %s already exists for job %s", catalog_collection, self.job_id)
                return True  # Collection exists

            if response.status_code == HTTP_404_NOT_FOUND:
                # If status is not found, create collection body and try to post it.
                self.logger.info(
                    "Catalog collection %s not found; creating it for job %s",
                    catalog_collection,
                    self.job_id,
                )
                minimal_collection = get_minimal_collection_body(catalog_collection)
                self.logger.debug("Minimal collection body for job %s: %s", self.job_id, minimal_collection)
                create_response = requests.post(
                    f"{self.catalog_url}/catalog/collections",
                    headers={
                        **self.auth_headers,
                        "Content-Type": "application/json",
                    },
                    data=dumps(minimal_collection),
                    timeout=5,
                )
                create_response.raise_for_status()
                self.logger.info(
                    "Catalog collection %s creation finished for job %s with status %s",
                    catalog_collection,
                    self.job_id,
                    create_response.status_code,
                )
                return create_response.status_code == HTTP_201_CREATED

            response.raise_for_status()

        except (RequestException, JSONDecodeError, RuntimeError) as exc:
            # If anything fails, log failure and exit.
            self.logger.exception(
                "Catalog collection check/create failed for job %s collection %s: %s",
                self.job_id,
                catalog_collection,
                exc,
            )
            self.log_job_execution(JobStatus.failed, 0, f"Failed to create catalog collection: {exc}")
        return False

    async def check_catalog(self, catalog_collection: str, features: list[Feature]) -> bool:
        """
        Method used to check RSPY catalog if a feature from input_collection is already published.

        Args:
            catalog_collection (str): Name of the catalog collection.
            features (list): list of features to process.

        Returns:
            bool: True in case of success, False otherwise
        """
        exists = await asyncio.to_thread(self.check_if_collection_exists, catalog_collection)
        if not exists:
            # Stop catalog check if staging is unable to create the collection
            return False
        # Set the filter containing the item ids to be inserted
        # Get each feature id and create /catalog/search argument
        ids = [f"'{feature.id}'" for feature in features]
        filter_object = {
            "collections": catalog_collection,
            "filter-lang": "cql2-text",
            "filter": f"id IN ({','.join(ids)})",
            "limit": str(len(ids)),
        }

        search_url = f"{self.catalog_url}/catalog/search"
        self.logger.info(
            "Searching catalog for existing items for job %s; collection=%s, ids=%s",
            self.job_id,
            catalog_collection,
            [feature.id for feature in features],
        )
        self.logger.debug(
            "Catalog search request for job %s: url=%s, params=%s",
            self.job_id,
            search_url,
            filter_object,
        )

        try:
            response = await common_settings.http_client().get(
                search_url,
                headers=self.auth_headers,
                params=filter_object,
                timeout=5,
            )
            response.raise_for_status()  # Raise an error for HTTP error responses
            # check the response type
            item_collection = response.json()
            self.logger.debug("Catalog search response for job %s: %s", self.job_id, item_collection)
            if not item_collection.get("type") or item_collection.get("type") != "FeatureCollection":
                self.logger.error("Failed to search catalog, no expected response received")
                return False
            # for debugging only
            for item in item_collection.get("features"):
                self.logger.debug(f"Session {item.get('id')} has {len(item.get('assets'))} assets")

            self.create_streaming_list(features, item_collection)
            # Keep the input features for catalog items that have been logically expired or whose
            # asset payload has been removed by the catalog lifecycle: those items still exist in the
            # collection, but they are no longer downloadable and must be restaged and updated.
            # IMPORTANT: the responsability for updating the `expires` and `updated` fields should be on catalog side.
            self.expired_items = [
                item
                for item in features
                if item.id
                in {
                    catalog_item["id"]
                    for catalog_item in item_collection.get("features", [])
                    if catalog_item.get("properties", {}).get("unpublished") or not catalog_item.get("assets")
                }
            ]
            # Expired / assetless catalog items must also go through the streaming flow alongside new items.
            for item in self.expired_items:
                if item not in self.stream_list:
                    self.stream_list.append(item)
            self.logger.info(
                "Catalog check finished for job %s; new_items=%d, expired_items=%d",
                self.job_id,
                len(self.stream_list) - len(self.expired_items),
                len(self.expired_items),
            )
            return True
        except (RequestException, JSONDecodeError, RuntimeError) as exc:
            self.logger.exception("Catalog search failed for job %s: %s", self.job_id, exc)
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
                self.logger.info(
                    "No existing catalog items found for job %s; all %d features will be streamed",
                    self.job_id,
                    len(features),
                )
            else:
                # Do the difference, call rs-server-download only with features to be downloaded
                # Extract IDs from the catalog response directly
                already_downloaded_ids = {feature["id"] for feature in catalog_response["features"]}
                # Select only features whose IDs have not already been downloaded (returned in /search)
                not_downloaded_features = [item for item in features if item.id not in already_downloaded_ids]
                self.stream_list = not_downloaded_features
                self.logger.info(
                    "Prepared streaming list for job %s; already_in_catalog=%d, to_stream=%d",
                    self.job_id,
                    len(already_downloaded_ids),
                    len(self.stream_list),
                )
                self.logger.debug(
                    "Streaming feature ids for job %s: %s",
                    self.job_id,
                    [feature.id for feature in self.stream_list],
                )
        except KeyError as ke:
            self.logger.exception(
                f"The 'features' field is missing in the response from the catalog service. {ke}",
            )

            raise RuntimeError(
                "The 'features' field is missing in the response from the catalog service.",
            ) from ke

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
            - The S3 credentials (access key, secret key, endpoint, and region) are fetched from OSAM.
        """
        if not self.assets_info:
            self.logger.debug("Trying to remove file from bucket, but no asset info defined.")
            return

        # Use S3 object storage credentials of the logged user
        self.logger.info("Cleaning up %d staged asset(s) for job %s", len(self.assets_info), self.job_id)
        s3_handler = S3StorageHandler(authentication.get_s3_credentials(self.request))

        for s3_obj in self.assets_info:
            try:
                self.logger.debug(
                    "Deleting staged object for job %s from s3://%s/%s",
                    self.job_id,
                    s3_obj.s3_bucket,
                    s3_obj.s3_file,
                )
                s3_handler.delete_key_from_s3(s3_obj.s3_bucket, s3_obj.s3_file)
            except RuntimeError as error:
                self.logger.warning(
                    "Failed to delete from the bucket key s3://%s/%s : %s",
                    s3_obj.s3_bucket,
                    s3_obj.s3_file,
                    error,
                )
                continue

    def wait_for_dask_completion(self, client: Client):
        """Waits for all Dask tasks to finish before proceeding."""
        timeout = int(os.environ.get("RSPY_STAGING_TIMEOUT", 600))
        self.logger.info("Waiting for Dask task completion for job %s; timeout=%ss", self.job_id, timeout)
        while timeout > 0:
            if not client.call_stack():
                self.logger.debug("Dask call stack is empty for job %s", self.job_id)
                break  # No tasks running anymore
            time.sleep(1)
            timeout -= 1
        if timeout <= 0:
            self.logger.warning("Timed out while waiting for Dask completion for job %s", self.job_id)

    def publish_processed_features(self, catalog_collection: str, refresh_tokens: dict[str, RefreshTokenData]) -> bool:
        """Handles publishing features and cleanup in case of failure."""
        # Publish all the features once processed
        published_features_ids: list[str] = []
        expired_item_ids = {feature.id for feature in self.expired_items}
        self.logger.info(
            "Publishing %d processed feature(s) for job %s into collection %s",
            len(self.stream_list),
            self.job_id,
            catalog_collection,
        )
        for feature in self.stream_list:
            self.logger.info("Publishing processed feature %s for job %s", feature.id, self.job_id)
            publish_ok = (
                self.update_expired_rspy_feature(catalog_collection, feature)
                if feature.id in expired_item_ids
                else self.publish_rspy_feature(catalog_collection, feature)
            )
            if not publish_ok:
                # cleanup
                self.log_job_execution(
                    JobStatus.failed,
                    None,
                    f"The item {feature.id} couldn't be published in the catalog. Cleaning up",
                )

                # delete the files
                self.delete_files_from_bucket()
                # delete the published items
                self.unpublish_rspy_features(catalog_collection, published_features_ids)
                self.unsubscribe_refresh_tokens(refresh_tokens)
                self.logger.error(f"The item {feature.id} couldn't be published in the catalog")
                return False
            if feature.id not in expired_item_ids:
                published_features_ids.append(feature.id)
        self.logger.info("Published processed features for job %s successfully", self.job_id)
        return True

    def unsubscribe_refresh_tokens(self, refresh_tokens: dict[str, RefreshTokenData]):
        """Unsubscribe all available refresh tokens."""
        self.logger.debug("Unsubscribing %d refresh token(s) for job %s", len(refresh_tokens), self.job_id)
        for refresh_token in refresh_tokens.values():
            if refresh_token:
                refresh_token.unsubscribe(self.logger)

    @staticmethod
    def valid_asset_size(size_bytes: int | None) -> bool:
        """Return whether the source size is known and non-negative."""
        return size_bytes is not None and size_bytes >= 0

    @staticmethod
    def coerce_content_length(value: str | int | None, asset: AssetInfo) -> int:
        """Validate a provider size before including it in the job total."""
        if value is None:
            raise RuntimeError(f"Missing Content-Length for source asset {asset.product_url}")
        if isinstance(value, bool):
            raise RuntimeError(f"Invalid Content-Length for source asset {asset.product_url}: {value!r}")
        try:
            size_bytes = int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid Content-Length for source asset {asset.product_url}: {value!r}") from exc
        if size_bytes < 0:
            raise RuntimeError(f"Invalid negative Content-Length for source asset {asset.product_url}: {value!r}")
        return size_bytes

    def resolve_http_asset_size(
        self,
        asset: AssetInfo,
        refresh_tokens: dict[str, RefreshTokenData],
    ) -> int:
        """Resolve an HTTP/HTTPS source size using HEAD and Content-Length."""
        refresh_token = refresh_tokens.get(asset.domain, None)
        try:
            response = requests.head(
                asset.product_url,
                auth=TokenAuth(refresh_token.get_access_token()) if refresh_token else None,
                allow_redirects=True,
                timeout=60,
            )
            response.raise_for_status()
        except RequestException as exc:
            raise RuntimeError(
                f"Failed to retrieve Content-Length for source asset {asset.product_url}: {exc}",
            ) from exc
        return self.coerce_content_length(response.headers.get("Content-Length"), asset)

    def resolve_s3_asset_size(self, asset: AssetInfo) -> int:
        """Resolve an external S3 source size using HeadObject and ContentLength."""
        source_url = urlparse(asset.product_url)
        source_bucket = source_url.netloc
        source_key = source_url.path.lstrip("/")
        if not source_bucket or not source_key:
            raise RuntimeError(f"Invalid S3 source URL for asset size resolution: {asset.product_url}")

        try:
            source_s3_client = boto3.client(
                "s3",
                endpoint_url=asset.external_s3_endpoint_url,
                aws_access_key_id=asset.external_s3_access_key,
                aws_secret_access_key=asset.external_s3_secret_key,
                use_ssl=True,
            )
            response = source_s3_client.head_object(Bucket=source_bucket, Key=source_key)
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as exc:
            raise RuntimeError(f"Failed to retrieve ContentLength for source asset {asset.product_url}: {exc}") from exc
        return self.coerce_content_length(response.get("ContentLength"), asset)

    def resolve_asset_sizes(self, refresh_tokens: dict[str, RefreshTokenData]):
        """Query the provider only for sizes missing from STAC metadata."""
        for asset in self.assets_info:
            # Prefer a validated STAC file:size and avoid an unnecessary provider request.
            if self.valid_asset_size(asset.size_bytes):
                continue

            # Fall back to the metadata operation supported by the source protocol.
            scheme = urlparse(asset.product_url).scheme
            if asset.origin_service == "s3" or scheme == "s3":
                asset.size_bytes = self.resolve_s3_asset_size(asset)
            elif scheme in {"http", "https"}:
                asset.size_bytes = self.resolve_http_asset_size(asset, refresh_tokens)
            else:
                # Without a source size, a reliable byte-weighted job total cannot be computed.
                raise RuntimeError(
                    f"Cannot determine the size of source asset {asset.product_url!r}: "
                    f"unsupported scheme {scheme!r} and no STAC file:size was provided.",
                )

            self.logger.info("Resolved size for source asset %s: %s bytes", asset.product_url, asset.size_bytes)

    def submit_dask_task(
        self,
        task_env: dict[str, str],
        client: Client,
        asset: AssetInfo,
        refresh_tokens: dict[str, RefreshTokenData],
        s3_credentials: S3Credentials,
        try_token_refresh: bool = False,
        progress_queue=None,
    ) -> Future:
        """Submit the streaming task to Dask."""

        # refresh the token if needed
        refresh_token = refresh_tokens.get(asset.domain, None)
        self.logger.debug(
            "Submitting Dask streaming task for job %s; asset=%s, bucket=%s, domain=%s, refresh=%s",
            self.job_id,
            asset.s3_file,
            asset.s3_bucket,
            asset.domain,
            try_token_refresh,
        )
        if refresh_token and try_token_refresh and not update_station_token(refresh_token, self.logger):
            raise RuntimeError(f"Could not retrieve or refresh the token for {asset}")

        return client.submit(
            streaming_task,
            task_env,
            asset,
            refresh_token.config if refresh_token else None,
            TokenAuth(refresh_token.get_access_token()) if refresh_token else None,
            s3_credentials,
            progress_queue,
        )

    def manage_dask_tasks(
        self,
        client: Client,
        catalog_collection: str,
        refresh_tokens: dict[str, RefreshTokenData],
    ):  # pylint: disable=too-many-branches, too-many-statements
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
            refresh_tokens (dict[str, RefreshTokenData]): The authentication data per domain,
            including the station access token.

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
            self.unsubscribe_refresh_tokens(refresh_tokens)
            return

        # Get the S3 object storage credentials for the logged user
        s3_credentials = authentication.get_s3_credentials(self.request)
        self.logger.debug("Retrieved S3 credentials object for job %s", self.job_id)

        # Prepare environment to trace Dask tasks with OpenTelemetry.
        task_env = self._prepare_env_with_trace_context()

        # Track assets independently so parallel workers and retries cannot double-count bytes.
        asset_sizes = {asset.s3_file: asset.size_bytes or 0 for asset in self.assets_info}
        asset_progress = {asset.s3_file: 0 for asset in self.assets_info}
        total_bytes = sum(asset_sizes.values())
        progress_lock = threading.Lock()
        last_reported_progress = {"value": int(self.progress)}

        def record_asset_progress(
            asset_key: str,
            bytes_delta: int = 0,
            reset: bool = False,
            complete: bool = False,
        ):
            """Aggregate per-asset byte progress and update the job percentage."""
            if total_bytes <= 0:
                return

            with progress_lock:
                asset_size = asset_sizes.get(asset_key, 0)
                if reset:
                    # Each attempt starts at byte zero; remove progress from a failed attempt.
                    asset_progress[asset_key] = 0
                elif complete:
                    # A successful future confirms that the full source asset was streamed.
                    asset_progress[asset_key] = asset_size
                else:
                    asset_progress[asset_key] = min(
                        asset_size,
                        asset_progress.get(asset_key, 0) + max(int(bytes_delta), 0),
                    )

                downloaded_bytes = sum(asset_progress.values())
                # Integer arithmetic avoids rounding drift; 100 is reserved for final success.
                progress = min(99, downloaded_bytes * 100 // total_bytes)
                if progress > last_reported_progress["value"]:
                    last_reported_progress["value"] = progress
                    self.log_job_execution(
                        JobStatus.running,
                        progress,
                        f"Downloaded {downloaded_bytes / (1024**2):.2f} / {total_bytes / (1024**2):.2f} MiB",
                    )

        progress_queue: DaskQueue | None = None
        progress_stop_event = threading.Event()
        progress_thread = None

        if total_bytes > 0:
            try:
                # Share this scheduler-backed proxy with every worker and the local monitor.
                progress_queue = DaskQueue(name=f"staging-progress-{self.job_id}", client=client)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self.logger.warning("Could not create Dask progress queue. Falling back to task completion: %s", exc)

        def monitor_progress_queue(queue: DaskQueue):
            """Consume worker byte deltas while submitted futures are running."""
            while not progress_stop_event.is_set():
                try:
                    message = queue.get(timeout=1)
                except (Empty, TimeoutError):
                    continue
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    if not progress_stop_event.is_set():
                        self.logger.warning("Stopping staging progress monitor after queue error: %s", exc)
                    break

                if not isinstance(message, dict):
                    continue
                asset_key = message.get("asset")
                if not asset_key:
                    continue
                if message.get("reset"):
                    record_asset_progress(asset_key, reset=True)
                elif "bytes" in message:
                    record_asset_progress(asset_key, bytes_delta=message["bytes"])

        def stop_progress_monitor():
            """Stop the listener and release its scheduler-backed queue."""
            progress_stop_event.set()
            if progress_thread and progress_thread.is_alive():
                progress_thread.join(timeout=5)
            if progress_queue and hasattr(progress_queue, "close"):
                try:
                    progress_queue.close()
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    self.logger.debug("Failed to close Dask progress queue: %s", exc)

        if progress_queue:
            progress_thread = threading.Thread(
                target=monitor_progress_queue,
                args=(progress_queue,),
                name=f"staging-progress-{self.job_id}",
                daemon=True,
            )
            progress_thread.start()

        # prevent submitting more tasks than necessary.
        # this can occur when the number of tasks that can run in parallel
        # exceeds the actual number of tasks intended for submission.
        max_parallel_tasks = min(sum(client.nthreads().values()), len(self.assets_info))
        self.logger.info(f"Number of tasks asigned to the initial batch: {max_parallel_tasks}")
        self.logger.debug(
            "Dask task scheduling state for job %s: worker_threads=%s, asset_count=%d",
            self.job_id,
            client.nthreads(),
            len(self.assets_info),
        )
        # convert to iterator for dynamic updates
        data_iter = iter(self.assets_info)
        future_to_asset: dict[Future, AssetInfo] = {}

        def submit_next_task(try_token_refresh: bool = False) -> Future:
            asset = next(data_iter)
            # Dask serializes the existing Queue proxy, keeping both ends on the same queue.
            future = self.submit_dask_task(
                task_env,
                client,
                asset,
                refresh_tokens,
                s3_credentials,
                try_token_refresh,
                progress_queue,
            )
            future_to_asset[future] = asset
            return future

        try:
            # initial dataset
            initial_batch_tasks = {submit_next_task() for _ in range(max_parallel_tasks)}
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.exception(f"Submitting task to dask cluster failed. Reason: {e}")
            stop_progress_monitor()
            self.log_job_execution(JobStatus.failed, None, f"Submitting task to dask cluster failed. Reason: {e}")
            self.unsubscribe_refresh_tokens(refresh_tokens)
            return
        # counter to be used for percentage
        completed_tasks = 0
        tasks = as_completed(initial_batch_tasks)
        for task in tasks:
            try:
                res = task.result()  # This will raise the exception from the task if it failed
                self.logger.debug(f"Task result = {res}")
                completed_tasks += 1
                self.logger.info(
                    "Completed streaming task %d/%d for job %s",
                    completed_tasks,
                    len(self.assets_info),
                    self.job_id,
                )
                asset = future_to_asset.pop(task, None)
                if asset:
                    record_asset_progress(asset.s3_file, complete=True)
                elif total_bytes <= 0:
                    self.log_job_execution(
                        JobStatus.running,
                        min(99, round(completed_tasks * 100 / len(self.assets_info))),
                        "In progress",
                    )
                self.logger.debug("%s Task streaming completed", task.key)
                # Submit a new task if available and no errors occurred
                try:
                    next_task = submit_next_task(try_token_refresh=True)
                    tasks.add(next_task)
                    next_asset = future_to_asset[next_task]
                    self.logger.debug("Queued next asset %s for job %s", next_asset.s3_file, self.job_id)
                except StopIteration:
                    # Scheduling is exhausted, but active futures can still report progress.
                    self.logger.debug("No more Dask tasks to queue for job %s", self.job_id)
            except Exception as task_e:  # pylint: disable=broad-exception-caught
                self.logger.error("Task failed with exception: %s", task_e)
                client.cancel(tasks)
                # Wait for all the current running tasks to complete.
                self.wait_for_dask_completion(client)
                stop_progress_monitor()
                # Update status for the job
                self.log_job_execution(JobStatus.failed, None, f"At least one of the tasks failed: {task_e}")
                self.delete_files_from_bucket()
                self.unsubscribe_refresh_tokens(refresh_tokens)
                self.logger.error(f"Tasks monitoring finished with error. At least one of the tasks failed: {task_e}")
                return

        # The as_completed loop exits only after every dynamically added future finishes.
        stop_progress_monitor()

        if not self.publish_processed_features(catalog_collection, refresh_tokens):
            return

        # Update status once all features are processed
        self.log_job_execution(JobStatus.successful, 100, "Finished")
        # Update the subscribers for token refreshment
        self.unsubscribe_refresh_tokens(refresh_tokens)
        self.logger.info("Tasks monitoring finished")

    def _prepare_env_with_trace_context(self) -> dict[str, str]:
        """
        Prepare environment to trace dask tasks with opentelemetry.

        https://oneuptime.com/blog/post/2026-02-06-trace-python-subprocess-calls-opentelemetry/view#context-propagation-to-child-processes
        https://opentelemetry.io/docs/languages/python/propagation/#manual-context-propagation

        Args:
            catalog_collection (str): The catalog collection name for storing processed features.
        """
        env = os.environ.copy()

        # Inject trace context into environment variables
        carrier: dict[str, str] = {}
        inject(carrier)

        self.logger.info(f"OpenTelemetry carrier: {carrier!r}")

        # Convert carrier to environment variables
        if "traceparent" in carrier:
            env["TRACEPARENT"] = carrier["traceparent"]
        if "tracestate" in carrier:
            env["TRACESTATE"] = carrier["tracestate"]

        # Also pass as JSON for scripts that can parse it
        env["OTEL_TRACE_CONTEXT"] = json.dumps(carrier)

        return env

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
            (using environment variables `DASK_GATEWAY_ADDRESS` and `DASK_GATEWAY__AUTH__TYPE`) to
            retrieve a list of existing clusters.
        - If no clusters are available, it attempts to create a new cluster scheduler.

        Raises:
            RuntimeError: Raised if the cluster name is None, required environment variables are missing,
                        cluster creation fails or authentication errors occur.
            KeyError: Raised if the necessary Dask Gateway environment variables (`DASK_GATEWAY_ADDRESS`,
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
        self.logger.info("Connecting Dask client for staging job %s", self.job_id)
        if not self.cluster:
            # Connect to the gateway and get the list of the clusters
            try:
                # get the name of the cluster
                cluster_name = os.environ["RSPY_DASK_STAGING_CLUSTER_NAME"]
                # In local mode, authenticate to the dask cluster with username/password
                if common_settings.LOCAL_MODE:
                    self.logger.debug("Using BasicAuth for local Dask gateway connection")
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
                        self.logger.debug("Using JupyterHub auth for Dask gateway connection")
                        gateway_auth = JupyterHubAuth(api_token=os.environ["JUPYTERHUB_API_TOKEN"])
                    else:
                        self.logger.error(f"Unsupported authentication type: {auth_type}")
                        raise RuntimeError(f"Unsupported authentication type: {auth_type}")

                gateway = Gateway(
                    address=os.environ["DASK_GATEWAY_ADDRESS"],
                    auth=gateway_auth,
                )

                # Sort the clusters by newest first
                clusters = sorted(gateway.list_clusters(), key=lambda cluster: cluster.start_time, reverse=True)
                self.logger.debug(f"Cluster list for gateway {os.environ['DASK_GATEWAY_ADDRESS']!r}: {clusters}")

                # Get the identifier of the cluster whose name matches the cluster_name variable.
                # Protection for the case when this cluster does not exist.
                cluster_id = None
                self.logger.info(f"Requested cluster name: {cluster_name}")
                cluster_names = [
                    cluster.options.get("cluster_name") for cluster in clusters if isinstance(cluster.options, dict)
                ]

                self.logger.info(
                    f"Available cluster names: {cluster_names}",
                )
                cluster_id = next(
                    (
                        cluster.name
                        for cluster in clusters
                        if isinstance(cluster.options, dict) and cluster.options.get("cluster_name") == cluster_name
                    ),
                    None,
                )
                self.logger.info(f"Selected cluster id: {cluster_id}")

                if not cluster_id:
                    raise IndexError(f"Dask cluster with 'cluster_name'={cluster_name!r} was not found.")

                self.cluster = gateway.connect(cluster_id)
                self.logger.info(f"Successfully connected to the {cluster_name} dask cluster")

            except KeyError as e:
                self.logger.exception(
                    "Failed to retrieve the required connection details for "
                    "the Dask Gateway from one or more of the following environment variables: "
                    "DASK_GATEWAY_ADDRESS, RSPY_DASK_STAGING_CLUSTER_NAME, "
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
        self.logger.info("Dask client connected for staging job %s", self.job_id)

        # Forward logging from dask workers to the caller
        client.forward_logging()

        def set_dask_env(host_env: dict, env_var_names: list[str]):
            """Pass environment variables to the dask workers."""
            for name in ["USE_SSL"] + env_var_names:
                if name in host_env:
                    os.environ[name] = host_env[name]

        env_var_pattern = re.compile(r".*_(HOST|PORT|USER|PASS|CLIENT_CRT|CLIENT_KEY|CA_CRT)$")
        env_var_names = [key for key in os.environ if env_var_pattern.fullmatch(key)]
        # Dask workers run in separate processes/pods, so only connection-related
        # environment variables are copied across; values are intentionally not logged.
        self.logger.debug("Forwarding %d environment variable names to Dask workers", len(env_var_names))
        client.run(set_dask_env, os.environ, env_var_names)

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

        # Check the cluster dashboard
        self.logger.debug(f"Dask Client: {client} | Cluster dashboard: {self.cluster.dashboard_link}")

        return client

    def load_and_validate_external_auth_config(self, domain: str) -> ExternalAuthenticationConfig:
        """Load the external auth config for this domain and validates the authorization
        by checking if the user has the corresponding staging_download role."""
        try:
            self.logger.info("Loading external authentication config for domain %s", domain)
            external_auth_config = load_external_auth_config_by_domain(domain)
            if not external_auth_config:
                raise HTTPException(
                    status_code=401,
                    detail=f"Failed to retrieve the configuration for the station token of domain {domain}.",
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
                self.logger.info(
                    "Validated staging_download role for station %s and job %s",
                    external_auth_config.station_id,
                    self.job_id,
                )
            return external_auth_config

        except (ServiceNotFound, HTTPException) as e:
            self.logger.exception(f"{e}")
            raise RuntimeError(f"{e}") from e

    def get_refresh_token(self, external_auth_config: ExternalAuthenticationConfig) -> RefreshTokenData:
        """
        Find or create the shared refresh-token holder for an external station.

        Token holders are shared between concurrent staging jobs for the same
        station. The subscriber count prevents the background refresh mechanism
        from keeping unused tokens alive.

        Args:
            external_auth_config: Authentication settings for the external station.

        Returns:
            A RefreshTokenData instance with a valid access token.
        """
        # Find or create a token while holding the global list lock. Individual
        # token values are protected by their own padlock inside RefreshTokenData.
        self.logger.info("Getting refresh token for station %s", external_auth_config.station_id)
        with self.station_token_list_lock:
            for refresh_token in self.station_token_list:
                if refresh_token.station_id() == external_auth_config.station_id:
                    self.logger.debug(
                        "Reusing existing refresh token holder for station %s",
                        refresh_token.station_id(),
                    )
                    refresh_token.subscribe(self.logger)
                    break
            else:
                refresh_token = RefreshTokenData(external_auth_config)
                self.station_token_list.append(refresh_token)
                self.logger.debug("Created refresh token holder for station %s", refresh_token.station_id())

        if not update_station_token(refresh_token, self.logger):
            refresh_token.unsubscribe(self.logger)
            self.logger.error("Could not retrieve or refresh the station token.")
            raise RuntimeError("Could not retrieve or refresh the station token.")

        return refresh_token

    async def process_rspy_features(  # pylint: disable=too-many-return-statements, too-many-branches
        self,
        catalog_collection: str,
    ) -> tuple[str, dict]:
        """
        Method used to trigger dask distributed streaming process.

        It prepares one AssetInfo per asset, connects to Dask, loads the external
        station authentication needed by those assets, and delegates task monitoring
        to `manage_dask_tasks`. The Dask connection is intentionally created before
        token retrieval so we do not call external stations if the execution
        backend is unavailable.

        Args:
            catalog_collection (str): Name of the catalog collection.

        Returns:
            tuple: tuple of MIME type and process response (dictionary containing the job ID and a
                status message).
                Example: ("application/json", {"running": <job_id>})
        """
        self.logger.info(
            "Starting staging workflow for job %s; collection=%s, feature_count=%d",
            self.job_id,
            catalog_collection,
            len(self.stream_list),
        )
        self.logger.debug("Starting main loop")

        # Step 1: Convert each STAC asset into a concrete streaming task
        # description. This mutates the feature asset hrefs to their final S3
        # locations, so the later catalog publish uses the staged paths.
        try:
            for feature in self.stream_list:
                assets = getattr(feature, "assets", {})
                asset_count = len(assets) if isinstance(assets, dict) else 0
                self.logger.debug(
                    "Preparing streaming tasks for job %s feature %s with %d asset(s)",
                    self.job_id,
                    getattr(feature, "id", ""),
                    asset_count,
                )
                new_assets_info = prepare_streaming_tasks(
                    catalog_collection,
                    feature,
                    self.staging_user,
                    self.named_assets,
                )
                if new_assets_info is None:
                    return self.log_job_execution(JobStatus.failed, 0, "Unable to create tasks for the Dask cluster")
                self.assets_info += new_assets_info
                self.logger.debug(
                    "Prepared %d streaming task(s) for job %s feature %s",
                    len(new_assets_info),
                    self.job_id,
                    feature.id,
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.exception("Failed to prepare streaming tasks for job %s: %s", self.job_id, e)
            return self.log_job_execution(JobStatus.failed, 0, f"Error when preparing streaming tasks: {e}")

        if not self.assets_info:
            self.logger.info("There are no assets to stage. Exiting....")
            return self.log_job_execution(JobStatus.successful, 100, "Finished without processing any tasks")

        # Step 2: Determine which external domains require station tokens.
        # External S3 assets already carry S3 credentials from config, so they do
        # not need a station token and are represented by the synthetic "s3" domain.
        domains = list(
            {asset.domain for asset in self.assets_info if asset.origin_service != "s3"},
        )
        self.logger.info(f"Staging from domain(s) {domains}")
        if not domains:
            # If we got 0 domain, it means we only have assets from external s3 buckets
            domains = ["s3"]
        self.logger.debug("Authentication domains for job %s after normalization: %s", self.job_id, domains)

        # Step 3: Connect to Dask before retrieving station tokens. This avoids
        # unnecessary external-auth calls if the execution backend is unavailable.
        try:
            dask_client = self.dask_cluster_connect()
        except RuntimeError as run_time_error:
            self.logger.error("Failed to start the staging process")
            return self.log_job_execution(JobStatus.failed, 0, str(run_time_error))

        refresh_tokens: dict[str, RefreshTokenData] = {}
        # Step 4: Retrieve station tokens only for domains that require them.
        try:
            for domain in domains:
                self.logger.debug("Preparing authentication for job %s domain %s", self.job_id, domain)
                if domain not in ("s3", "FTP"):
                    external_auth_config = self.load_and_validate_external_auth_config(domain)
                    if external_auth_config.auth_type:
                        refresh_tokens[domain] = self.get_refresh_token(external_auth_config)
                elif domain == "FTP" and not LOCAL_MODE:
                    self.logger.info("Staging from FTP server, no token retrieval needed")
                    # FTP staging does not use bearer tokens, but in cluster mode
                    # each unique FTP station still requires `staging_download`.
                    from rs_server_common.authentication.authentication import (  # pylint: disable=C0415
                        auth_validation,
                    )

                    for station, _ in {
                        S3StorageHandler.parse_ftps_path(asset.product_url) for asset in self.assets_info
                    }:
                        # for each unique station, validate the api key roles
                        auth_validation(
                            station,
                            "staging_download",
                            request=self.request,
                            staging_process=True,
                        )
        except RuntimeError as rte:
            self.logger.error(f"Failed to start the staging process: {rte}")
            return self.log_job_execution(JobStatus.failed, 0, f"Loading station token service failed: {rte}")

        # Resolve every source size before submission so progress can use a byte-weighted job total.
        try:
            self.resolve_asset_sizes(refresh_tokens)
        except RuntimeError as rte:
            self.logger.error(f"Failed to start the staging process: {rte}")
            self.unsubscribe_refresh_tokens(refresh_tokens)
            return self.log_job_execution(JobStatus.failed, 0, f"Resolving source asset sizes failed: {rte}")

        self.log_job_execution(JobStatus.running, 0, "Sending tasks to the dask cluster")

        # Step 5: Manage Dask callbacks in a worker thread so the FastAPI event
        # loop remains responsive while `as_completed` waits for task results.
        self.logger.debug("Starting tasks monitoring thread")
        try:
            with init_opentelemetry.start_span(
                __name__,
                f"[{self.staging_user}:{catalog_collection}] staging_dask_tasks",
            ):
                await asyncio.to_thread(
                    self.manage_dask_tasks,
                    dask_client,
                    catalog_collection,
                    refresh_tokens,
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            self.logger.exception("Task monitoring thread failed for job %s: %s", self.job_id, e)
            self.log_job_execution(JobStatus.failed, 0, f"Error from tasks monitoring thread: {e}")

        # cleanup by disconnecting the dask client
        self.assets_info = []
        dask_client.close()
        self.logger.info("Finished staging workflow for job %s with status %s", self.job_id, self.status.value)

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
            include all the necessary attributes required by the catalog.

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
        publish_url = f"{self.catalog_url}/catalog/collections/{catalog_collection}/items"
        self.logger.info(
            f"Adding the following catalog item {feature.id} in collection {catalog_collection}; method POST",
        )
        return self._send_feature_to_catalog("post", publish_url, feature)

    def update_expired_rspy_feature(self, catalog_collection: str, feature: Feature) -> bool:
        """
        Updates an expired feature already present in the catalog.

        The feature is sent through the catalog PUT endpoint with refreshed assets.
        """
        update_url = f"{self.catalog_url}/catalog/collections/{catalog_collection}/items/{feature.id}"
        self.logger.info(f"Updating expired catalog item {feature.id} in collection {catalog_collection}; method PUT")
        return self._send_feature_to_catalog("put", update_url, feature)

    def _send_feature_to_catalog(
        self,
        method: str,
        url: str,
        feature: Feature,
    ) -> bool:
        """
        Send a staged feature to the catalog using the shared HTTP flow for both creation and update.

        This helper is used by the two catalog write paths:
        - `POST` for features that are newly staged and do not yet exist in catalog
        - `PUT` for expired features that already exist in catalog and must be updated

        Before sending the feature, the method removes any `alternate` asset links so the
        catalog payload only contains the refreshed staged asset hrefs. It then serializes
        the STAC item, sends it to the given catalog endpoint, and retries on timeout using
        the staging retry configuration.

        Args:
            method (str): HTTP method to use, expected to be `post` or `put`.
            url (str): Full catalog endpoint URL that will receive the STAC item.
            feature (Feature): The staged feature to send, including updated asset paths.

        Returns:
            bool: `True` if the catalog request succeeds, `False` if a non-retryable error
            occurs or all timeout retries are exhausted.
        """

        # Remove alternate asset links before sending the STAC item back to catalog,
        # regardless of whether the item is created or updated.
        for asset in feature.assets.values():
            if hasattr(asset, "alternate"):
                del asset.alternate  # type: ignore
        self.logger.debug("Catalog payload for item %s after alternate cleanup: %s", feature.id, feature.model_dump())

        if method == "post":
            error_context = "publishing items"
            self.logger.debug(f"Item {feature.id} is being published with {len(feature.assets)} assets")
        else:
            error_context = "updating expired item"
            self.logger.debug(f"Item {feature.id} is being updated with {len(feature.assets)} assets")

        request_method = requests.post if method == "post" else requests.put

        attempt = 0
        while attempt <= self.catalog_publish_max_retries:
            try:
                self.logger.debug(
                    f"Sending {method.upper()} request for item {feature.id} to {url} "
                    f"(attempt {attempt + 1}/{self.catalog_publish_max_retries + 1})",
                )
                response = request_method(
                    url,
                    headers={
                        **self.auth_headers,
                        "Content-Type": "application/geo+json",
                    },
                    data=feature.model_dump_json(),
                    timeout=self.catalog_publish_timeout,
                )
                response.raise_for_status()
                self.logger.debug(
                    "Catalog %s response for item %s: status=%s, body=%s",
                    method.upper(),
                    feature.id,
                    response.status_code,
                    response.text,
                )

                if method == "post":
                    self.logger.info(f"Item {feature.id} was published successfully in catalog")
                else:
                    self.logger.info(f"Expired catalog item {feature.id} was updated successfully")
                # Treat HTTP 409 as success (happens for concurrent staging of the same data)
                if response.status_code != HTTP_409_CONFLICT:
                    response.raise_for_status()  # Raise an error for HTTP error responses
                return True
            except requests.exceptions.Timeout as exc:
                if attempt >= self.catalog_publish_max_retries:
                    self.logger.error(f"Error while {error_context} in rspy catalog {exc}")
                    return False
                # Retry transient timeout errors before failing the whole staging flow.
                self.logger.warning(
                    f"Timeout while {error_context} in rspy catalog. "
                    f"Retry {attempt + 1}/{self.catalog_publish_max_retries} in {self.catalog_publish_retry_delay}s",
                )
                time.sleep(self.catalog_publish_retry_delay)
                attempt += 1
            except (RequestException, JSONDecodeError) as exc:
                self.logger.error(f"Error while {error_context} in rspy catalog {exc}")
                return False

        self.logger.error(f"Exhausted all retries while {error_context} for item {feature.id}")
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
            self.logger.info(
                "Unpublishing %d catalog item(s) from collection %s after staging rollback",
                len(feature_ids),
                catalog_collection,
            )
            for feature_id in feature_ids:
                catalog_delete_item = f"{self.catalog_url}/catalog/collections/{catalog_collection}/items/{feature_id}"
                self.logger.debug("Deleting catalog item %s using %s", feature_id, catalog_delete_item)
                response = requests.delete(
                    catalog_delete_item,
                    headers=self.auth_headers,
                    timeout=3,
                )
                response.raise_for_status()  # Raise an error for HTTP error responses
                self.logger.info("Deleted catalog item %s during rollback", feature_id)
        except (RequestException, JSONDecodeError) as exc:
            self.logger.error("Error while deleting the item from rspy catalog %s", exc)

    def __repr__(self):
        """Returns a string representation of the Staging processor."""
        return "RSPY Staging OGC API Processor"


# Register the processor
processors = {"Staging": Staging}
