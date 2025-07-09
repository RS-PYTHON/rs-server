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
from datetime import datetime

from fastapi import FastAPI, Request
from rs_server_catalog.timestamps_extension import ISO_8601_FORMAT
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from stac_fastapi.pgstac.core import CoreCrudClient


class DataLifecycle:

    def __init__(self, app: FastAPI, client: CoreCrudClient):
        """
        Initialize the data lifecycle management. Will run a periodic task to:

        - Retrieve all expired items (expired field <= current_date() and unpublished field not set).

        - For each asset of these items: remove the the associated file from the S3 bucket, remove the asset from the item.

        - Set the unpublished field of the STAC item to current date using PATCH item catalog endpoint

        Args:
            app: FastAPI application
            client: Associated CoreCrudClient instance
            task: Periodic task
            period: Period in seconds between the end of a management task and the start of a new one. If <0, the
            task is deactivated.
            cancel: Cancel the task
        """
        self.logger = Logging.default(__name__)
        self.app: FastAPI = app
        self.client: CoreCrudClient = client
        self.task: Task | None = None
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
                self.task = asyncio.create_task(self._periodic())

    async def _periodic(self):
        """Run the periodic task"""
        while not self.cancel_flag:
            try:
                # Current datetime
                now = datetime.now().strftime(ISO_8601_FORMAT)

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

                filter = json.dumps(filter)
                items = await self.client.get_search(
                    self.request,
                    filter_expr=filter,
                    filter_lang="cql2-json",
                    limit=100,
                )
                bp = 0

            except Exception:
                self.logger.error(traceback.format_exc())

            # Wait n seconds before next run
            if self.cancel_flag:
                return
            await asyncio.sleep(self.period)

    async def cancel(self):
        """Cancel the periodic task"""
        self.cancel_flag = True
        if not self.task:
            return

        # See: https://superfastpython.com/asyncio-periodic-task/#How_to_Run_a_Periodic_Task
        self.task.cancel()
        try:
            await self.task
        except Exception:
            self.logger.error(traceback.format_exc())
