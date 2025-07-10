# Copyright 2025 CS Group
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

"""Data lifecycle management"""

import asyncio
import json
import os
import traceback
from asyncio import Task
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from rs_server_catalog.timestamps_extension import ISO_8601_FORMAT
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.pgstac.transactions import BulkTransactionsClient
from stac_fastapi.types.stac import Item, ItemCollection

# Number of items to search in a single database request
ITEM_LIMIT = 100


class DataLifecycle:

    def __init__(self, app: FastAPI, client_search: CoreCrudClient):
        """
        Initialize the data lifecycle management. Will run a periodic task to:

        - Retrieve all expired items (expired field <= current_date() and unpublished field not set).

        - For each asset of these items: remove the the associated file from the S3 bucket, remove the asset from the item.

        - Set the unpublished field of the STAC item to current date using PATCH item catalog endpoint

        Args:
            app: FastAPI application
            client_search: CoreCrudClient instance for searching items
            client_bulk: BulkTransactionsClient instance for bulk update
            periodic_task: Periodic task
            period: Period in seconds between the end of a management task and the start of a new one. If <0, the
            task is deactivated.
            cancel: Cancel the task
        """
        self.logger = Logging.default(__name__)
        self.app: FastAPI = app
        self.client_search: CoreCrudClient = client_search
        self.client_bulk = BulkTransactionsClient()
        self.s3_handler = S3StorageHandler()
        self.periodic_task: Task | None = None
        self.period: float = float(os.getenv("RSPY_DATA_LIFECYCLE_PERIOD", -1))
        self.cancel_flag: bool = False

        # We need a fake request instance to work with the database
        scope = {
            "app": self.app,
            "type": "http",
            "method": "GET",
            "path": "dummy-path",
            "headers": {},
        }
        self.request = Request(scope=scope)
        self.request._base_url = "http://dummy-url"

    async def run(self):
        """Trigger the periodic task"""
        if (self.period >= 0) and (not self.cancel_flag):
            with init_opentelemetry.start_span(__name__, "data_lifecycle"):
                self.periodic_task = asyncio.create_task(self._periodic())

    async def cancel(self):
        """Cancel the periodic task"""
        self.cancel_flag = True
        if not self.periodic_task:
            return

        # See: https://superfastpython.com/asyncio-periodic-task/#How_to_Run_a_Periodic_Task
        self.periodic_task.cancel()
        try:
            await self.periodic_task
        except Exception:
            self.logger.error(traceback.format_exc())

    async def _periodic(self):
        """Run the periodic task"""
        while not self.cancel_flag:
            try:
                # Current datetime
                now: str = datetime.now().strftime(ISO_8601_FORMAT)

                # Filter on expired items that have not already been unpublished.
                # TODO: improve the filter on the "expires" property,
                # see: https://pforge-exchange2.astrium.eads.net/jira/browse/RSPY-725
                filter = {
                    "op": "and",
                    "args": [
                        {"op": "<", "args": [{"property": "expires"}, now]},
                        {"op": "isNull", "args": [{"property": "unpublished"}]},
                    ],
                }

                # FOR TESTING ONLY
                filter = {}

                # Search the database. Call directly the stac_fastapi layer, not the rs-server-catalog
                # http endpoint, so we don't handle the /catalog prefix, the owner_id, the authentication, ...
                item_collection: ItemCollection = await self.client_search.get_search(
                    self.request,
                    filter_expr=json.dumps(filter),
                    filter_lang="cql2-json",
                    limit=ITEM_LIMIT,
                )
                items = item_collection.get("features", [])

                # Order assets by key=bucket name and value=list of bucket keys
                bucket_info: dict[str, list[str]] = defaultdict(list)

                # Update each item and update bucket info
                for item in items:
                    await self._manage_item(item, now, bucket_info)

                # First, delete all files from the buckets in parallel
                async with asyncio.TaskGroup() as task_group:
                    for bucket_name, bucket_keys in bucket_info.items():

                        # Do the search in a synchronized thread so we don't block the main thread,
                        # see: https://stackoverflow.com/a/71517830
                        task_group.create_task(
                            run_in_threadpool(self.s3_handler.delete_files_from_s3(bucket_name, bucket_keys)),
                        )

            except Exception:
                self.logger.error(traceback.format_exc())

            # Wait n seconds before next run
            if self.cancel_flag:
                return
            await asyncio.sleep(self.period)

    async def _manage_item(self, item: Item, now: str, bucket_info: dict[str, list[str]]):
        """
        Update a single item and update bucket info.

        Args:
            item: Item to clean
            now: current datetime
            bucket_info: bucket information to be updated
        """
        # Set the unpublished property to current datetime
        item.setdefault("properties", {})["unpublished"] = now

        # Remove all the assets from the item
        assets = item.pop("assets", {})
        item["assets"] = {}

        # Update bucket info for each asset file path
        for asset in assets.values():
            try:
                href = asset["alternate"]["s3"]["href"]
                parsed = urlparse(href)
                bucket_name = parsed.netloc
                bucket_key = parsed.path
                if (parsed.scheme.lower() != "s3") or (not bucket_name) or (not bucket_key):
                    raise KeyError()
                bucket_info[bucket_name].append(bucket_key)

            except KeyError:
                self.logger.debug(f"Asset has no valid href: {asset}")
