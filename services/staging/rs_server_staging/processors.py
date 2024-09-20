import asyncio  # for handling asynchronous tasks
import json
import logging
import os
import uuid
from enum import Enum
from typing import Any

import requests
import stac_pydantic
import tinydb  # temporary, migrate to psql
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


class CADIPStaging:
    BUCKET = os.getenv("RSPY_STORAGE", "s3://test")

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
            "RSPY_CATALOG_URL", "http://127.0.0.1:8003",
        )  # get catalog href, loopback else
        #################
        # Database section
        self.job_id = str(uuid.uuid4())  # Generate a unique job ID
        self.progress: int = 0
        self.status: ProcessorStatus = ProcessorStatus.CREATED
        self.tracker: tinydb = db
        self.create_job_execution()
        #################
        # Inputs section
        self.item_collection: dict = input_collection
        self.catalog_collection: str = collection
        self.catalog_item_name: str = item
        #################
        # Execution section
        self.check_catalog()
        # Start execution
        # self.process_feature()

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

    def check_catalog(self):
        # Get each asset id and create /catalog/search argument
        # Note, only for GET, to be updated and create request body for POST
        ids = [feature.id for feature in self.item_collection.features]
        # Creating the filter string
        filter_string = "id IN ({})".format(", ".join(["'{}'".format(id_) for id_ in ids]))

        # Final filter object
        filter_object = {"filter-lang": "cql2-text", "filter": filter_string}

        search_url = f"{self.catalog_url}/catalog/search"
        # forward apikey to access catalog
        # self.create_streaming_list(requests.get(search_url, headers=self.headers, params=filter_object, timeout=3).json())
        # not right now
        self.create_streaming_list(requests.get(search_url, params=json.dumps(filter_object), timeout=3).json())

    def create_streaming_list(self, catalog_response: dict):
        # Based on catalog response, pop out assets already in catalog
        if catalog_response["context"]["returned"] == len(self.item_collection.features):
            self.stream_list = []
        else:
            if not catalog_response["features"]:
                pass  # No search result found, process everything from self.item_collection
                # request.post('RS-server/download/feature/../, data=self.item_collection, headers=self.headers)
            else:
                # Do the difference, call rs-server-download only with features to be downloaded
                already_downloaded_features = stac_pydantic.ItemCollection(
                    id="in-memory",  # Replace with your desired collection ID
                    features=[stac_pydantic.Item(**feature) for feature in catalog_response["features"]],
                )
                ids2 = {item.id for item in already_downloaded_features.features}
                not_downloaded_features = [item for item in self.item_collection.features if item.id not in ids2]
                # request.post('RS-server/download/feature/../, data=not_downloaded_features, headers=self.headers)
                pass

    def __repr__(self):
        """Returns a string representation of the CADIPStaging processor."""
        return "CADIP Staging OGC API Processor"


# Register the processor
processors = {"CADIPStaging": CADIPStaging}
