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
# pylint: disable = wrong-import-order
import asyncio  # for handling asynchronous tasks
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from osam.tasks import (
    apply_user_access_policy,
    build_s3_rights,
    build_users_data_map,
    get_user_s3_credentials,
    link_rspython_users_and_obs_users,
    update_s3_rights_lists,
)
from rs_server_common.authentication import oauth2
from rs_server_common.middlewares import HandleExceptionsMiddleware, apply_middlewares
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from starlette.middleware.sessions import SessionMiddleware  # test if still needed
from starlette.requests import Request  # pylint: disable=C0411
from starlette.responses import JSONResponse
from starlette.status import (  # pylint: disable=C0411
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
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
    fastapi_app.extra["shutdown_event"] = threading.Event()
    # the trigger for running the logic in the background task
    fastapi_app.extra["users_sync_trigger"] = threading.Event()
    # save info for future requests of endpoint /storage/account/{user}/rights
    fastapi_app.extra["users_info"] = dict[str, Any]
    # start the background task in a thread using asyncio.to_thread
    fastapi_app.extra["refresh_task"] = asyncio.create_task(
        asyncio.to_thread(main_osam_task, DEFAULT_OSAM_FREQUENCY_SYNC),
    )
    # trigger the first run -> this was disabled by a request from ops
    # app.extra["users_sync_trigger"].set()
    # Yield control back to the application (this is where the app will run)
    yield

    # shutdown logic (cleanup)
    logger.info("Shutting down the application...")
    # cancel the refresh task and wait for it to exit cleanly
    fastapi_app.extra["shutdown_event"].set()
    # make the main_osam_task to exit from the wait sleeping
    fastapi_app.extra["users_sync_trigger"].set()

    refresh_task = fastapi_app.extra.get("refresh_task")
    if refresh_task:
        try:
            await refresh_task  # Ensure the task exits
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception(f"Exception during shutdown of background thread: {e}")
    logger.info("Application gracefully stopped...")


@router.post("/storage/accounts/update")
async def accounts_update():
    """
    Triggers the synchronization of Keycloak and OVH (OBS) account information.

    This endpoint sets a flag to initiate a background task (`main_osam_task`) that performs the account linking
    logic between Keycloak and the Object Storage Access Manager (OSAM). It doesn't wait for a completion signal
    from the background task and returns a success response.

    Returns:
        JSONResponse: Always a success message saying that the sync algorythm of the accounts started.

    """
    # Trigger the background task. This was also requested by the operations team: the endpoint should return
    # immediately to the user without waiting for the algorithm to complete.
    app.extra["users_sync_trigger"].set()
    return JSONResponse(
        status_code=HTTP_200_OK,
        content="The algorithm for updating the Keycloak and OVH accounts has been initiated. "
        "The process duration may vary depending on the number of accounts to be updated.",
    )


def get_user_rights(user):
    """
    Retrieves and constructs the S3 access rights policy for a specified user.

    This function:
      - Looks up the user's Keycloak roles from the in-memory user store.
      - Parses the roles to determine S3 access permissions (read, read+download, write+download).
      - Generates a full S3 access policy document using predefined templates.

    Args:
        user (str): Username of the account for which to retrieve access rights.

    Returns:
        dict: The constructed S3 access policy for the specified user.

    Raises:
        HTTPException: If the user is not found in the in-memory Keycloak user store (HTTP 404).
    """

    if user not in app.extra["users_info"]:
        return None
    logger.debug(f"Building the rights for user {user}")
    s3_rights = build_s3_rights(app.extra["users_info"][user])
    return update_s3_rights_lists(s3_rights)


@router.get("/storage/account/{user}/update")
async def apply_user_obs_access_policy(request: Request, user: str):  # pylint: disable=unused-argument
    """
    Applies the S3 access policy for a given user.

    This endpoint:
      - Retrieves the user's current rights based on Keycloak roles.
      - Applies the corresponding s3 access policy via the object storage provider,
      by calling the ovh endpoint

    Args:
        request (Request): FastAPI request object (currently unused).
        user (str): Username of the account for which to apply access rights.

    Returns:
        JSONResponse: A JSON response confirming that the access policy has been applied.
    """

    logger.debug("Endpoint for applying the user access policy")
    current_rights = get_user_rights(user)
    if not current_rights:
        raise HTTPException(HTTP_404_NOT_FOUND, f"User '{user}' does not exist in keycloak")
    status_code = HTTP_200_OK
    result, msg = apply_user_access_policy(user, json.dumps(current_rights))
    if not result:
        status_code = HTTP_400_BAD_REQUEST
    return JSONResponse(status_code=status_code, content=msg)


@router.get("/storage/account/{user}/rights")
async def user_rights(request: Request, user: str):  # pylint: disable=unused-argument
    """
    Retrieves the S3 access rights policy for a given user.

    This endpoint:
      - Returns the full S3 access policy as determined from the user's Keycloak roles.

    Args:
        request (Request): FastAPI request object (currently unused).
        user (str): Username of the account for which to retrieve access rights.

    Returns:
        JSONResponse: A JSON response containing the user's S3 access rights policy.
    """

    logger.debug("Endpoint for getting the user rights")
    output = get_user_rights(user)
    if not output:
        raise HTTPException(HTTP_404_NOT_FOUND, f"User '{user}' does not exist in keycloak")
    return JSONResponse(status_code=HTTP_200_OK, content=json.loads(json.dumps(output)))


@router.get("/storage/account/credentials")
async def get_credentials(request: Request):
    """Endpoint used to get user credentials from cloud provider.
    Request MUST contain oauth2 cookie in header"""
    auth_info = await oauth2.get_user_info(request)
    logger.info(f"Getting ovh s3 credentials for keycloak user {auth_info.user_login}")
    return get_user_s3_credentials(auth_info.user_login)


def main_osam_task(timeout: int = 60):
    """
    Asynchronous background task that periodically links RS-Python users to observation users.

    This function continuously waits for either a shutdown signal or an external trigger (`users_sync_trigger`)
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
    logger.info(f"Timeout {timeout} for triggering the sync of keycloak and ovh accounts is disabled")
    while True:
        try:
            # Wait for either the trigger action (from endpoint) or the timeout before starting the refresh process
            # for getting attributes from keycloack
            # Later Edit: The timeout was disabled because of the request from ops team
            # if this is wanted later, just add `timeout=timeout` as input param in wait()
            triggered = app.extra["users_sync_trigger"].wait()
            if app.extra["shutdown_event"].is_set():  # If shutting down, exit loop
                logger.info("Shutting down background thread and exit")
                break

            if triggered:  # If triggered, prepare for the next one
                logger.debug("Releasing users_sync_trigger")
                app.extra["users_sync_trigger"].clear()

            logger.info("Starting the sync process between keycloak accounts and ovh accounts")

            link_rspython_users_and_obs_users()
            app.extra["users_info"] = build_users_data_map()

            logger.info("Sync process finished")

        except Exception as e:  # pylint: disable=broad-exception-caught
            # Handle cancellation properly even for asyncio.CancelledError (for example when FastAPI shuts down)
            logger.exception(f"Handle cancellation: {e}")
            # let's continue
    logger.info("Exiting from the getting keycloack attributes thread !")


# Health check route
@router.get("/_mgmt/ping", include_in_schema=False)
async def ping():
    """Liveliness probe."""
    return JSONResponse(status_code=HTTP_200_OK, content="Healthy")


app.include_router(router)
app.add_middleware(HandleExceptionsMiddleware)
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("RSPY_COOKIE_SECRET", ""))
app = apply_middlewares(app)
app.router.lifespan_context = app_lifespan  # type: ignore
init_opentelemetry.init_traces(app, "osam.service")
