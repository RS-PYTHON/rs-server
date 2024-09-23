import asyncio  # for handling asynchronous tasks
import json
import logging
import os
import uuid
from enum import Enum
from functools import wraps
from typing import Any

import requests
import tinydb  # temporary, migrate to psql
from fastapi import HTTPException
from starlette.datastructures import Headers
from pygeoapi.process.base import BaseProcessor


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

    def __init__(self, credentials: Headers, input_collection: Any, collection: str, item: str, db: tinydb, **kwargs):
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
        self.progress: int = 0
        self.tracker: tinydb = db
        self.create_job_execution()
        #################
        # Inputs section
        self.item_collection: dict = input_collection
        self.catalog_collection: str = collection
        self.catalog_item_name: str = item

    def execute(self):
        self.log_job_execution(ProcessorStatus.CREATED)
        # Execution section
        self.check_catalog()
        # Start execution
        self.process_rspy_features()
        [self.publish_rspy_feature(feature) for feature in self.stream_list]
        # self.publish_rspy_feature(self.item_collection.features[0])

    def create_job_execution(self):
        # Create job id and track it
        self.tracker.insert(
            {"job_id": self.job_id, "status": ProcessorStatus.to_json(self.status), "progress": self.progress},
        )

    def log_job_execution(self, status: ProcessorStatus = None, progress: int = None):
        # Update both runtime and db status and progress
        self.status = status if status else self.status
        self.progress = progress if progress else self.progress
        tiny_job = tinydb.Query()
        self.tracker.update(
            {"status": ProcessorStatus.to_json(self.status), "progress": self.progress},
            tiny_job.job_id == self.job_id,
        )

    """Template functions"""

    async def process_feature(self):
        """
        Processes each feature in the input collection, downloading assets for features
        not already in the catalog, and then creating an item in the catalog.

        This function tracks the progress and sets the job to 100% when all items are processed.
        """
        task_progress = 0
        total_items = len(self.item_collection["features"])
        created_items = []

        for feature in self.item_collection["features"]:
            if not self.in_catalog(feature):
                for asset in feature["assets"]:
                    await self.download(asset)
                    task_progress += 100 / total_items / len(feature["assets"])
                    logging.info(f"Task progress: {task_progress:.2f}%")

                # Create an item in the catalog using provided metadata
                created_items.append(self.create_catalog_item(feature))

        # Set job progress to 100% once all items are processed
        task_progress = 100
        logging.info(f"Task completed. Progress set to {task_progress}%.")

        # Return a STAC ItemCollection containing created items
        return self.create_stac_item_collection(created_items)

    async def download(self, asset: dict):
        """
        Download the asset using streaming to the catalog bucket.

        :param asset: The asset metadata to download.
        """
        # from rs-server.cadip.download import StreamDownload
        # StreamDownload(asset, BUCKET_LOC)

        logging.info(f"Downloading asset {asset['href']} to {self.BUCKET}...")
        # Simulating streaming download
        await asyncio.sleep(1)  # Simulate asynchronous download
        logging.info(f"Download complete for asset {asset['href']}.")

    def create_catalog_item(self, feature):
        """
        Creates a catalog item using the provided STAC item metadata.

        :param feature: The feature to be added to the catalog.
        :return: The created catalog item.
        """
        logging.info(f"Creating catalog item for feature {feature['id']}...")
        # Placeholder for catalog item creation logic
        # This would likely involve an API call to publish the item.
        return feature

    def create_stac_item_collection(self, created_items: list):
        """
        Creates a STAC ItemCollection from a list of created items.

        :param created_items: The list of items created.
        :return: A STAC ItemCollection object.
        """
        logging.info("Creating STAC ItemCollection from created items.")
        return {"type": "FeatureCollection", "features": created_items}

    """End of template"""

    def check_catalog(self):
        # Get each asset id and create /catalog/search argument
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
        except (
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
            json.JSONDecodeError,
        ) as e:
            # logger.error here soon
            self.log_job_execution(ProcessorStatus.FAILED)

    def create_streaming_list(self, catalog_response: dict):
        # Based on catalog response, pop out assets already in catalog and prepare rest for download
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

    def process_rspy_features(self):
        self.log_job_execution(ProcessorStatus.IN_PROGRESS)
        # foreach feature in streaming_list, async start download, and check progress
        # request.post('RS-server/download/feature/../, data=self.stream_list.idx, headers=self.headers)
        stream_url = f"{self.download_url}/cadip/streaming"
        for feature in self.stream_list:
            try:
                response = requests.post(stream_url, data=feature.json(), timeout=3)
                response.raise_for_status()
            except (
                requests.exceptions.HTTPError,
                requests.exceptions.Timeout,
                requests.exceptions.RequestException,
                requests.exceptions.ConnectionError,
                json.JSONDecodeError,
            ) as e:
                # logger.error here soon
                self.log_job_execution(ProcessorStatus.FAILED)

    def publish_rspy_feature(self, feature: dict):
        # how to get user? // Do we need user? should /catalog/collection/collectionId/items works with apik?
        publish_url = f"{self.catalog_url}/catalog/collections/test_owner:{self.catalog_collection}/items"
        try:
            response = requests.post(publish_url, data=feature.json(), timeout=3)
            response.raise_for_status()  # Raise an error for HTTP error responses
            self.create_streaming_list(response.json())
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
