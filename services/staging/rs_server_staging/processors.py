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
import time
import uuid
from enum import Enum
from functools import wraps
from typing import Any, Dict

import aiohttp
import dask
import requests
import stac_pydantic
import tinydb  # temporary, migrate to psql
from dask.distributed import Client, LocalCluster
from dask.distributed.protocol import serialize
from fastapi import HTTPException
from pygeoapi.process.base import BaseProcessor
from requests.auth import AuthBase
from rs_server_common.authentication.authentication_to_external import (
    get_station_token,
    load_external_auth_config_by_station_service,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from rs_server_common.utils.logging import Logging
from starlette.datastructures import Headers
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_302_FOUND,
    HTTP_307_TEMPORARY_REDIRECT,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_424_FAILED_DEPENDENCY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)


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


def check_status(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.status == ProcessorStatus.FAILED:
            raise HTTPException(detail=f"Cannot perform {func}, processor status is FAILED.", status_code=200)
        return func(self, *args, **kwargs)

    return wrapper


class MethodWrapperMeta(type):
    def __new__(cls, name, bases, attrs):
        # Wrap all callable attributes with check_status, to
        for attr_name, attr_value in attrs.items():
            if callable(attr_value):
                attrs[attr_name] = check_status(attr_value)
        return super().__new__(cls, name, bases, attrs)


# Custom authentication class
class TokenAuth(AuthBase):
    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        # Add the Authorization header to the request
        r.headers["Authorization"] = f"Bearer {self.token}"
        r.headers["Content-Type"] = "application/x-www-form-urlencoded"
        return r


@dask.delayed
def streaming_download(rspy_asset: Dict[str, stac_pydantic.shared.Asset], auth: str):

    try:
        product_url = rspy_asset.get("href")
        product_name = rspy_asset.get("title")
    except KeyError as kerr_msg:
        # raise HTTPException(
        #         detail=f"Missing key in asset dictionary! {kerr_msg}",
        #         status_code=HTTP_404_NOT_FOUND,
        #     )
        return False
    s3_handler = S3StorageHandler(
        os.environ["S3_ACCESSKEY"],
        os.environ["S3_SECRETKEY"],
        os.environ["S3_ENDPOINT"],
        os.environ["S3_REGION"],  # "sbg",
    )
    try:
        # path to be updated
        time.sleep(4)
        s3_handler.s3_streaming_upload(product_url, auth, "rs-cluster-catalog", f"stream/{product_name}")
    except RuntimeError as exc:
        # raise HTTPException(
        #         detail=exc,
        #         status_code=HTTP_424_FAILED_DEPENDENCY,
        #     )
        return False
    return True


class RSPYStaging(BaseProcessor):  # (metaclass=MethodWrapperMeta): - meta for stopping actions if status is failed
    BUCKET = os.getenv("RSPY_CATALOG_BUCKET", "s3://test")
    status: ProcessorStatus = ProcessorStatus.QUEUED

    def __init__(
        self,
        credentials: Headers,
        input_collection: Any,
        collection: str,
        item: str,
        provider: str,
        db: tinydb,
        **kwargs,
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
        self.headers = credentials
        self.stream_list: list = []
        #################
        # Env section
        self.catalog_url = os.environ.get(
            "RSPY_HOST_CATALOG",
            "http://127.0.0.1:8003",
        )  # get catalog href, loopback else
        self.download_url = os.environ.get(
            "RSPY_RS_SERVER_CADIP_URL",
            "http://127.0.0.1:8000",
        )  # get  href, loopback else  to be removed
        #################
        # Database section
        self.job_id = str(uuid.uuid4())  # Generate a unique job ID
        self.detail = "Processing Unit was queued"
        self.progress: int = 0
        self.tracker: tinydb = db
        self.create_job_execution()
        #################
        # Inputs section
        self.item_collection: dict = input_collection
        self.catalog_collection: str = collection
        self.catalog_item_name: str = item
        self.provider = provider
        self.logger = Logging.default(__name__)

    async def execute(self):
        self.log_job_execution(ProcessorStatus.CREATED)
        # Execution section
        self.check_catalog()
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
        # Create job id and track it
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

    def check_catalog(self):
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

    async def make_request(self, session, asset, stream_url):
        """Helper function to make an HTTP POST request asynchronously."""
        try:
            # fixmeeee ?!
            converted_dict = {key: json.loads(value) for key, value in asset.items()}
            async with session.post(stream_url, json=converted_dict) as response:
                response.raise_for_status()
                return response
                # if response.status == 200:
                #     response_data = await response.json()
                #     return response_data
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            json.JSONDecodeError,
        ) as e:
            # Log the error and update the status
            self.log_job_execution(ProcessorStatus.FAILED)
            return None

    # @dask.delayed

    async def process_rspy_features(self):
        # Process each feature, by starting streaming download of its assets to final bucket
        self.log_job_execution(ProcessorStatus.IN_PROGRESS)
        # stream_url = f"{self.download_url}/cadip/{self.provider}/streaming"
        # total_assets_to_be_processed = sum(len(feature.assets) for feature in self.stream_list)
        # set_eodag_auth_token(f"{self.provider.lower()}", "cadip")
        token = get_station_token(
            load_external_auth_config_by_station_service(self.provider.lower(), self.provider),
        )

        # async with aiohttp.ClientSession() as session:
        # tasks = []
        # gateway = Gateway("http://127.0.0.1:8000")
        # try:
        #     dask_clusters_list = gateway.list_clusters()
        # except Exception as e:
        #     self.logger.debug(f"dask_clusters_list exccept= {e}")
        #     return
        # self.logger.debug(f"dask_clusters_list = {dask_clusters_list}")
        # if len(dask_clusters_list) > 0:
        #     cluster = gateway.connect(dask_clusters_list[0].name)
        # else:
        #     cluster = gateway.new_cluster()
        # self.logger.debug(f"cluster name = {cluster.name}")
        # List of options available
        # options = gateway.cluster_options()
        # print(f"{options.worker_cores}")

        # for key in options.keys():
        #    print(f"{key}: {options[key]}")

        # cluster = gateway.new_cluster(options)
        # self.logger.debug(f"cluster name with options = {cluster.name}")
        # gateway.scale_cluster(cluster.name, 2)
        # cluster.adapt(minimum=2, maximum=10)
        # Connect the client to the cluster
        # client = Client(cluster)
        # client = cluster.get_client()
        # self.logger.debug(f"Cluster dashboard: {cluster.dashboard_link}")
        # dask_clusters_list = gateway.list_clusters()
        # self.logger.debug(f"dask_clusters_list = {dask_clusters_list}")
        cluster = LocalCluster()
        client = Client(cluster)
        tasks = []
        # Check the cluster dashboard
        print(f"Cluster dashboard: {cluster.dashboard_link}")
        for feature in self.stream_list:
            for asset_name, asset_content in feature.assets.items():
                # fixmeee 1 how asset should be passed in order to be jsonified
                # tasks.append(self.make_request(session, {asset_name: asset_content.json()}, stream_url))
                # send the job to dask cluster
                # self.streaming_download(asset_content.dict(), TokenAuth(token))
                tasks.append(dask.delayed(streaming_download)(asset_content.dict(), TokenAuth(token)))
                # f = client.submit(streaming_download, asset_content.dict(),TokenAuth(token))

            # for index, asset in enumerate(asyncio.as_completed(tasks)):
            #     response = await asset
            #     if response:
            #         self.progress = ((index + 1) / total_assets_to_be_processed) * 100
            #         self.log_job_execution(ProcessorStatus.IN_PROGRESS, self.progress, detail=f"Processed {asset}")
            #     else:
            #         # If the result is None, it means the request failed
            #         # If one asset failed, should we push the feature to catalog?
            #         self.log_job_execution(ProcessorStatus.FAILED, self.progress, detail=f"Failed process: {asset}")
            try:
                final_result = dask.compute(tasks)
                self.logger.debug(f"final_result = {final_result}")
                await self.publish_rspy_feature(feature)
            except Exception as e:
                self.logger.exception(f"Exception: {e}")

        time.sleep(20)
        client.close()
        cluster.close()
        # Update status once all features are processed
        self.log_job_execution(ProcessorStatus.FINISHED, 100, detail="Finished")

    async def publish_rspy_feature(self, feature: dict):
        # Publish feature to catalog
        # how to get user? // Do we need user? should /catalog/collection/collectionId/items works with apik?
        publish_url = f"{self.catalog_url}/catalog/collections/{self.catalog_collection}/items"
        try:
            response = requests.post(publish_url, data=feature.json(), timeout=3)
            response.raise_for_status()  # Raise an error for HTTP error responses
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            json.JSONDecodeError,
        ) as e:
            # logger.error here soon
            self.log_job_execution(ProcessorStatus.FAILED)

    def __repr__(self):
        """Returns a string representation of the RSPYStaging processor."""
        return "RSPY Staging OGC API Processor"


# Register the processor
processors = {"RSPYStaging": RSPYStaging}
