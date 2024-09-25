import asyncio  # for handling asynchronous tasks
import json
import logging
import os
import uuid
from enum import Enum
from functools import wraps
from typing import Any

import aiohttp
import requests
import tinydb  # temporary, migrate to psql
from fastapi import HTTPException
from pygeoapi.process.base import BaseProcessor
from starlette.datastructures import Headers


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


class CADIPStaging(BaseProcessor):  # (metaclass=MethodWrapperMeta): - meta for stopping actions if status is failed
    BUCKET = os.getenv("RSPY_STORAGE", "s3://test")
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
        Initialize the CADIPStaging processor with the input collection and catalog details.

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
            "RSPY_CATALOG_URL",
            "http://127.0.0.1:8003",
        )  # get catalog href, loopback else
        self.download_url = os.environ.get(
            "RSPY_RS_SERVER_CADIP_URL",
            "http://127.0.0.1:8000",
        )  # get catalog href, loopback else
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

    async def process_rspy_features(self):
        # Process each feature, by starting streaming download of its assets to final bucket
        self.log_job_execution(ProcessorStatus.IN_PROGRESS)
        stream_url = f"{self.download_url}/cadip/{self.provider}/streaming"
        total_assets_to_be_processed = sum(len(feature.assets) for feature in self.stream_list)
        async with aiohttp.ClientSession() as session:
            tasks = []
            for feature in self.stream_list:
                for asset_name, asset_content in feature.assets.items():
                    # fixmeee 1 how asset should be passed in order to be jsonified
                    tasks.append(self.make_request(session, {asset_name: asset_content.json()}, stream_url))

                for index, asset in enumerate(asyncio.as_completed(tasks)):
                    response = await asset
                    if response:
                        self.progress = ((index + 1) / total_assets_to_be_processed) * 100
                        self.log_job_execution(ProcessorStatus.IN_PROGRESS, self.progress, detail=f"Processed {asset}")
                    else:
                        # If the result is None, it means the request failed
                        # If one asset failed, should we push the feature to catalog?
                        self.log_job_execution(ProcessorStatus.FAILED, self.progress, detail=f"Failed process: {asset}")
                await self.publish_rspy_feature(feature)
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
        """Returns a string representation of the CADIPStaging processor."""
        return "CADIP Staging OGC API Processor"


# Register the processor
processors = {"CADIPStaging": CADIPStaging}
