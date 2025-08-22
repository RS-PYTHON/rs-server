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
import copy
import json
import math
import os
import time
import traceback
from asyncio import Task
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from rs_server_catalog.timestamps_extension import ISO_8601_FORMAT
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from stac_fastapi.extensions.third_party import bulk_transactions
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.pgstac.transactions import BulkTransactionsClient
from stac_fastapi.types.stac import Item, ItemCollection
from starlette.datastructures import URL

# Number of items to search in a single database request
ITEM_LIMIT = 100


class DataLifecycle:
    """
    Initialize the data lifecycle management (cleaning of old assets). Will run a periodic task to:

    - Retrieve all expired items (expired field <= current_date() and unpublished field not set).

    - For each asset of these items: remove the the associated file from the S3 bucket,
        remove the asset from the item.

    - Set the unpublished and updated fields of the STAC item to current date using PATCH item catalog endpoint.

    Args:
        app: FastAPI application
        client_search: CoreCrudClient instance for searching items
        client_bulk: BulkTransactionsClient instance for bulk update
        periodic_task: Periodic task
        period: Period in seconds between two tasks. If <0, the task is deactivated.
        cancel: Cancel the task
        fake_request: Fake HTTP request
    """

    def __init__(self, app: FastAPI, client_search: CoreCrudClient):
        """Constructor"""
        self.logger = Logging.default(__name__)
        self.app: FastAPI = app
        self.client_search: CoreCrudClient = client_search
        self.client_bulk = BulkTransactionsClient()
        self.periodic_task: Task | None = None
        self.period: float = float(os.getenv("RSPY_DATA_LIFECYCLE_PERIOD") or -1)
        self.cancel_flag: bool = False
        self.fake_request = self.get_fake_request()

    def get_fake_request(self, extra_scope: dict | None = None) -> Request:
        """
        Return a fake request instance to work with the database.

        Args:
            extra_scope: Extra scope values
        """
        scope = {
            "app": self.app,
            "type": "http",
            "method": "GET",
            "path": "dummy-path",
            "headers": {},
        } | (extra_scope or {})
        request = Request(scope=scope)
        request._base_url = URL("https://dummy-url")  # pylint: disable=protected-access
        return request

    async def cancel(self):
        """Cancel the periodic task"""
        self.cancel_flag = True
        if not self.periodic_task:
            return

        # See: https://superfastpython.com/asyncio-periodic-task/#How_to_Run_a_Periodic_Task
        self.periodic_task.cancel()
        try:
            await self.periodic_task
        except asyncio.exceptions.CancelledError:  # NOSONAR - see https://github.com/python/cpython/issues/103486
            pass

    def run(self):
        """Trigger the periodic task in a distinct thread and exit."""
        if (self.period >= 0) and (not self.cancel_flag):
            self.periodic_task = asyncio.create_task(self._periodic_loop())

    async def _periodic_loop(self):
        """Run the periodic task in an infinite loop."""
        # Infinite loop
        while not self.cancel_flag:
            start_time = time.time()
            try:
                # Run the task
                with init_opentelemetry.start_span(__name__, "data_lifecycle"):
                    await self.periodic_once()

            # Log any error
            except Exception:  # pylint: disable=broad-exception-caught
                self.logger.error(traceback.format_exc())

            # If the caller cancelled execution, we exit the infinite loop before the sleep.
            if self.cancel_flag:
                return

            # Measure execution time of the task in seconds
            runtime = time.time() - start_time

            # We remove this execution time to the period in seconds between two tasks,
            # so the tasks run at fixed intervals.
            # If the current task took more time than the period, then a task was skipped, we don't run it.
            runtime = runtime % self.period
            sleep_value = self.period - runtime

            # Wait n seconds before next run
            if sleep_value != math.inf:
                self.logger.debug(f"Wait {str(timedelta(seconds=round(sleep_value)))} before next cleaning")
            await asyncio.sleep(sleep_value)

    async def periodic_once(self, genuine_request: Request | None = None):
        """
        Run the periodic task once.

        Args:
            genuine_request: request coming from the http endpoint. Only in local mode and from the pytests.
        """
        # Current datetime
        now: str = datetime.now().strftime(ISO_8601_FORMAT)

        # Filter on expired items that have not already been unpublished
        _filter = {
            "op": "and",
            "args": [
                {"op": "<", "args": [{"property": "expires"}, now]},
                {"op": "isNull", "args": [{"property": "unpublished"}]},
            ],
        }

        # Search the database. We call directly the stac_fastapi layer, not the rs-server-catalog
        # http endpoint, so we don't handle the /catalog prefix, the owner_id, the authentication, ...
        item_collection: ItemCollection = await self.client_search.get_search(
            genuine_request or self.fake_request,
            filter_expr=json.dumps(_filter),
            filter_lang="cql2-json",
            limit=ITEM_LIMIT,
        )
        items: list[Item] = item_collection.get("features", [])

        if items:
            self.logger.debug(f"Clean {len(items)} items")
        else:
            self.logger.debug("No items to clean")
            return

        # Order assets by key=bucket name and value=list of bucket keys
        bucket_info: dict[str, list[str]] = defaultdict(list)

        # Update each item locally and update bucket info
        for item in items:
            self._update_local_item(item, now, bucket_info)

        # Order the items by collection_name
        items_by_collection: dict[str, list[Item]] = defaultdict(list)
        for item in items:
            items_by_collection[item["collection"]].append(item)

        # First, update the items in the stac database using a bulk transaction.
        # We need one transaction by collection name, run in parallel.
        async with asyncio.TaskGroup() as task_group:
            for col_name, col_items in items_by_collection.items():

                # Convert the items into a dict with key=item id and value=items
                bulk_items = bulk_transactions.Items(
                    items={item["id"]: item for item in col_items},
                    method=bulk_transactions.BulkTransactionMethod.UPSERT,
                )

                # The collection name goes into the fake request endpoint path
                extra_scope = {"path_params": {"collection_id": col_name}}
                if genuine_request:
                    bulk_request = copy.copy(genuine_request)
                    bulk_request.scope = copy.copy(genuine_request.scope)
                    bulk_request.scope.update(extra_scope)
                else:
                    bulk_request = self.get_fake_request(extra_scope)

                # Run the bulk transaction.
                # NOTE: we call directly the stac_fastapi layer, not the rs-server-catalog http endpoint
                self.logger.debug(await self.client_bulk.bulk_item_insert(bulk_items, bulk_request))

        # Then, delete all files from the buckets in parallel.
        # NOTE: if ever this fails, a secondary data lifecycle is set on OVH Object Storage side to clean up
        # automatically the files on the buckets.
        # This is done 24 hours after the expiration delay set on the config map.
        async with asyncio.TaskGroup() as task_group:
            for bucket_name, bucket_keys in bucket_info.items():
                # Use a new s3 S3StorageHandler instance for every task as it is not thread-safe
                task_group.create_task(
                    S3StorageHandler().adelete_files_from_s3(bucket_name, bucket_keys),
                )
        self.logger.debug("Finished deleting s3 keys")

    def _update_local_item(self, item: Item, now: str, bucket_info: dict[str, list[str]]):
        """
        Update a single item instance locally and update bucket info.

        Args:
            item: Item to clean
            now: current datetime
            bucket_info: bucket information to be updated
        """
        # Set the updated and unpublished properties to current datetime
        item.setdefault("properties", {})["updated"] = now
        item.setdefault("properties", {})["unpublished"] = now

        # Remove all the assets from the item
        assets = item.get("assets", {})
        item["assets"] = {}

        # Remove the links. We don't need to save them in stac.
        # They are automatically generated at runtime with GET requests.
        item["links"] = []

        # Update bucket info for each existing asset file path
        for asset in assets.values():
            try:
                href = asset["href"]
                parsed = urlparse(href)
                bucket_name = parsed.netloc
                bucket_key = parsed.path.strip("/")
                if (parsed.scheme.lower() != "s3") or (not bucket_name) or (not bucket_key):
                    raise KeyError()
                bucket_info[bucket_name].append(bucket_key)

            except KeyError:
                self.logger.debug(f"Asset has no valid href: {asset}")
