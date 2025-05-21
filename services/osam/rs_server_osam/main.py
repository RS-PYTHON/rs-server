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

"""osam main module."""

import asyncio  # for handling asynchronous tasks
import logging
import os
import time
from contextlib import asynccontextmanager

# from dask.distributed import LocalCluster
from fastapi import APIRouter, FastAPI
from starlette.responses import JSONResponse
from starlette.status import (  # pylint: disable=C0411
    HTTP_200_OK,
)

from osam import opentelemetry
from osam.tasks import get_keycloak_configmap_values

DEFAULT_OSAM_FREQUENCY_SYNC = int(os.environ.get("DEFAULT_OSAM_FREQUENCY_SYNC", 10))

# Initialize a FastAPI application
app = FastAPI(title="osam-service", root_path="", debug=True)
router = APIRouter(tags=["OSAM service"])

logger = logging.getLogger("my_logger")
logger.setLevel(logging.DEBUG)


@asynccontextmanager
async def app_lifespan(fastapi_app: FastAPI):
    """Lifespann app to be implemented with start up / stop logic"""
    logger.info("Starting up the application...")
    fastapi_app.extra["shutdown_event"] = asyncio.Event()
    # the following event may be called from the future endpoint requested in rspy 606
    fastapi_app.extra["keycloack_event"] = asyncio.Event()
    # Run the refresh loop in the background
    fastapi_app.extra["refresh_task"] = asyncio.get_event_loop().create_task(
        main_osam_task(timeout=DEFAULT_OSAM_FREQUENCY_SYNC),
    )
    # Yield control back to the application (this is where the app will run)
    yield

    # Shutdown logic (cleanup)
    logger.info("Shutting down the application...")
    # Cancel the refresh task and wait for it to exit cleanly
    fastapi_app.extra["shutdown_event"].set()
    refresh_task = fastapi_app.extra.get("refresh_task")
    if refresh_task:
        refresh_task.cancel()
        try:
            await refresh_task  # Ensure the task exits
        except asyncio.CancelledError:
            pass  # Ignore the cancellation exception
    logger.info("Application gracefully stopped...")


async def main_osam_task(timeout: int = 60):
    
    logger.info("Starting the main background thread ")
    original_timeout = timeout
    while True:
        try:
            # Wait for either the shutdown event or the timeout before starting the refresh process
            # for getting attributes from keycloack

            await asyncio.wait(
                {
                    asyncio.create_task(app.extra["shutdown_event"].wait()),
                    asyncio.create_task(app.extra["keycloack_event"].wait()),
                },
                timeout=original_timeout,  # Wait up to timeout seconds before waking up
                return_when=asyncio.FIRST_COMPLETED,
            )

            if app.extra["shutdown_event"].is_set():  # If shutting down, exit loop
                logger.info("Finishing the main background thread  and exit")
                break
            if app.extra["keycloack_event"].is_set():  # If shutting down, exit loop
                logger.debug("Releasing keycloack_event")
                app.extra["keycloack_event"].release()

            logger.debug("Starting the process to get the keycloack attributes ")

            kc_user, _ = get_keycloak_configmap_values()
            print(kc_user) # debug
            # logic here
            # get the keycloack users



            logger.debug("Getting the keycloack attributes finished")

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Handle cancellation properly even for asyncio.CancelledError (for example when FastAPI shuts down)
            logger.exception(f"Handle cancellation: {e}")
            break
    logger.info("Exiting from the getting keycloack attributes thread !")
    return


# Health check route
@router.get("/_mgmt/ping", include_in_schema=False)
async def ping():
    """Liveliness probe."""
    return JSONResponse(status_code=HTTP_200_OK, content="Healthy")


app.include_router(router)
app.router.lifespan_context = app_lifespan  # type: ignore
opentelemetry.init_traces(app, "osam.service")
