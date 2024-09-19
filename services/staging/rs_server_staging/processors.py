import asyncio  # for handling asynchronous tasks
import logging
import os
import uuid
from enum import Enum

import tinydb  # temporary, migrate to psql


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

    def __init__(self, input_collection: dict, collection: str, item: str, db: tinydb, **kwargs):
        """
        Initialize the CADIPStaging processor with the input collection and catalog details.

        :param input_collection: The input collection of items to process.
        :param collection: The collection to use in the catalog.
        :param item: The item to process.
        :param kwargs: Additional keyword arguments.
        """
        #################
        # Env section
        self.catalog_url = os.environ.get("RSPY_CATALOG_URL", "http://127.0.0.1:800")  # get catalog href, loopback else
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

    def in_catalog(self, feature):
        """
        Checks if a feature exists in the RS catalog.

        :param feature: The feature to check.
        :return: True if the feature is in the catalog, False otherwise.
        """
        logging.info(f"Checking if feature {feature['id']} is in the catalog...")
        # Placeholder for catalog search logic
        # from rs-server-catalog import search?
        # return search(feature)
        return False  # Assuming it is not in the catalog for now.

    def __repr__(self):
        """Returns a string representation of the CADIPStaging processor."""
        return "CADIP Staging OGC API Processor"


# Register the processor
processors = {"CADIPStaging": CADIPStaging}
