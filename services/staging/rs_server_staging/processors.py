import asyncio  # for handling asynchronous tasks
import logging
import os

from fastapi import HTTPException  # to handle HTTP 400 errors


class CADIPStaging:
    BUCKET = os.getenv("RSPY_STORAGE", "s3://test")

    def __init__(self, input_collection: dict, collection: str, item: str, **kwargs):
        """
        Initialize the CADIPStaging processor with the input collection and catalog details.

        :param input_collection: The input collection of items to process.
        :param collection: The collection to use in the catalog.
        :param item: The item to process.
        :param kwargs: Additional keyword arguments.
        """
        self.item_collection = input_collection
        self.catalog_collection = collection
        self.catalog_item_name = item

        # Check the input collection for required fields if validation is not handled elsewhere
        if not self.check_schema_validation():
            self.check_item_collection()

    def check_schema_validation(self):
        """
        Checks if the input data is validated by Pygeoapi using JSON Schema.
        If it is, skip manual validation.

        :return: True if schema validation is handled, False otherwise.
        """
        # Placeholder: Check if pygeoapi performs validation
        # If Pygeoapi handles validation, return True and skip manual checks.
        return False

    def check_item_collection(self):
        """
        Checks the input collection for the presence of all required information.
        Raises HTTP 400 error if any required information is missing.
        """
        if "features" not in self.item_collection or not self.item_collection["features"]:
            raise HTTPException(status_code=400, detail="Missing required features in item collection")

        for feature in self.item_collection["features"]:
            if "assets" not in feature or not feature["assets"]:
                raise HTTPException(status_code=400, detail="Missing required assets in features")

        logging.info("Item collection passed validation.")

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
