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
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from osam.tasks import (
    build_full_s3_rights,
    build_s3_rights,
    build_users_data_map,
    link_rspython_users_and_obs_users,
    update_s3_rights_lists,
)
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from starlette.requests import Request  # pylint: disable=C0411
from starlette.responses import JSONResponse
from starlette.status import (  # pylint: disable=C0411
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

# The default synchronization time of the keycloak users with the ovh users (twice per day)
DEFAULT_OSAM_FREQUENCY_SYNC = int(os.environ.get("DEFAULT_OSAM_FREQUENCY_SYNC", 43200))
# Default timeout of the synchronization logic (2 minutes)
DEFAULT_OSAM_SYNC_LOGIC_TIMEOUT_ENDPOINT = int(os.environ.get("DEFAULT_OSAM_SYNC_LOGIC_TIMEOUT_ENDPOINT", 120))

# Initialize a FastAPI application
app = FastAPI(title="osam-service", root_path="", debug=True)
router = APIRouter(tags=["OSAM service"])

logger = Logging.default(__name__)
logger.setLevel(logging.DEBUG)


@asynccontextmanager
async def app_lifespan(fastapi_app: FastAPI):
    """Lifespann app to be implemented with start up / stop logic"""
    logger.info("Starting up the application...")
    fastapi_app.extra["shutdown_event"] = asyncio.Event()
    # the trigger for running the logic in the background task
    fastapi_app.extra["endpoint_trigger"] = asyncio.Event()
    # event to signal completion of the background task
    fastapi_app.extra["task_completion"] = asyncio.Event()
    # Run the refresh loop in the background
    fastapi_app.extra["refresh_task"] = asyncio.get_event_loop().create_task(
        main_osam_task(timeout=DEFAULT_OSAM_FREQUENCY_SYNC),
    )
    fastapi_app.extra["users_info"] = dict[str, Any]
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


@router.post("/storage/accounts/update")
async def accounts_update():
    """
    Triggers the synchronization of Keycloak and OVH (OBS) account information.

    This endpoint sets a flag to initiate a background task (`main_osam_task`) that performs the account linking
    logic between Keycloak and the Object Storage Access Manager (OSAM). It waits for a completion signal
    from the background task and returns a success or failure response based on the outcome.

    Returns:
        JSONResponse: A success message if the background task completes in time.

    Raises:
        HTTPException (500): If the background task times out or a runtime error occurs.
    """
    try:
        # Clear any previous completion signal
        app.extra["task_completion"].clear()
        # Trigger the background task
        app.extra["endpoint_trigger"].set()
        # Wait for the background task to signal completion with a timeout
        try:
            await asyncio.wait_for(
                app.extra["task_completion"].wait(),
                timeout=DEFAULT_OSAM_SYNC_LOGIC_TIMEOUT_ENDPOINT,
            )
        except TimeoutError:
            logger.error(f"Background task timed out after {DEFAULT_OSAM_SYNC_LOGIC_TIMEOUT_ENDPOINT} seconds")
            return HTTPException(
                HTTP_500_INTERNAL_SERVER_ERROR,
                "Failed to update accounts: Background task timed out after 30 seconds",
            )
        return JSONResponse(status_code=HTTP_200_OK, content="Keycloak and OVH accounts updated")
    except RuntimeError as rt:
        logger.error(f"Failed to update accounts: {rt}")
        return HTTPException(
            HTTP_500_INTERNAL_SERVER_ERROR,
            f"Failed to update the keycloak and ovh accounts. Reason: {rt}",
        )


@router.get("/storage/account/{user}/rights")
async def user_rights(request: Request, user: str):  # pylint: disable=unused-argument
    """Builds the s3 rights list"""
    logger.debug("Endpoint for getting the user rights")
    if user not in app.extra["users_info"]:
        return HTTPException(HTTP_404_NOT_FOUND, f"User '{user}' does not exist in keycloak")
    logger.debug(f"Building the rights for user {app.extra['users_info'][user]}")
    s3_rights = build_s3_rights(app.extra["users_info"][user])
    # s3_rights = {   'read': [   'rspython-ops-catalog-antoine-production/*/s1-l1/',
    #             'rspython-ops-catalog-antoine-s3-hkm/*/s1-l1/',
    #             'rspython-ops-catalog-copernicus-s1-l1/*/s1-l1/',
    #             'rspython-ops-catalog-default-s1-l1/*/s1-l1/',
    #             'rspython-ops-catalog-jules-production/*/s1-l1/',
    #             'rspython-ops-catalog/*/s1-l1/'],
    # 'read_download': [   'rspython-ops-catalog-default-s1-l1/agrosu/*/',
    #                      'rspython-ops-catalog-default-s1-l1/osam/s1-l1/',
    #                      'rspython-ops-catalog-emilie-s1-aux-infinite/agrosu/*/',
    #                      'rspython-ops-catalog/agrosu/*/',
    #                      'rspython-ops-catalog/osam/s1-l1/'],
    # 'write_download': [   'rspython-ops-catalog-default-s1-l1/osam/s1-l1/',
    #                       'rspython-ops-catalog/osam/s1-l1/']
    #                       }
    output = update_s3_rights_lists(s3_rights)
    return JSONResponse(status_code=HTTP_200_OK, content=output)


async def main_osam_task(timeout: int = 60):
    """
    Asynchronous background task that periodically links RS-Python users to observation users.

    This function continuously waits for either a shutdown signal or an external trigger (`endpoint_trigger`)
    to perform synchronization of Keycloak user attributes using `link_rspython_users_and_obs_users()`.
    The loop exits gracefully on shutdown signal.

    Args:
        timeout (int, optional): Number of seconds to wait before checking for shutdown or trigger events.
                                 Defaults to 60 seconds.

    Returns:
        None

    Raises:
        RuntimeError: This function does not explicitly raise `RuntimeError`, but any internal failure
                      is logged, and the task continues unless a shutdown signal is received.
    """
    logger.info("Starting the main background thread ")
    original_timeout = timeout
    while True:
        try:
            # Wait for either the shutdown event or the timeout before starting the refresh process
            # for getting attributes from keycloack

            await asyncio.wait(
                {
                    asyncio.create_task(app.extra["shutdown_event"].wait()),
                    asyncio.create_task(app.extra["endpoint_trigger"].wait()),
                },
                timeout=original_timeout,  # Wait up to timeout seconds before waking up
                return_when=asyncio.FIRST_COMPLETED,
            )

            if app.extra["shutdown_event"].is_set():  # If shutting down, exit loop
                logger.info("Finishing the main background thread  and exit")
                break
            if app.extra["endpoint_trigger"].is_set():  # If triggered, prepare for the next one
                logger.debug("Releasing endpoint_trigger")
                app.extra["endpoint_trigger"].clear()

            logger.debug("Starting the process to get the keycloack attributes ")

            link_rspython_users_and_obs_users()
            app.extra["users_info"] = build_users_data_map()

            # Signal completion to the endpoint
            app.extra["task_completion"].set()

            logger.debug("Getting the keycloack attributes finished")

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Handle cancellation properly even for asyncio.CancelledError (for example when FastAPI shuts down)
            logger.exception(f"Handle cancellation: {e}")
            # let's continue
    logger.info("Exiting from the getting keycloack attributes thread !")
    return


# Health check route
@router.get("/_mgmt/ping", include_in_schema=False)
async def ping():
    """Liveliness probe."""
    return JSONResponse(status_code=HTTP_200_OK, content="Healthy")


app.include_router(router)
app.router.lifespan_context = app_lifespan  # type: ignore
init_opentelemetry.init_traces(app, "osam.service")
