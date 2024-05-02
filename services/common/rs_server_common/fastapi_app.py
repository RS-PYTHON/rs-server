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

"""Init the FastAPI application."""

import asyncio
import typing
from contextlib import asynccontextmanager
from os import environ as env
from typing import Callable

import httpx
import sqlalchemy
from fastapi import APIRouter, Depends, FastAPI
from rs_server_common import settings
from rs_server_common.authentication import apikey_security
from rs_server_common.db.database import sessionmanager
from rs_server_common.schemas.health_schema import HealthSchema
from rs_server_common.utils import opentelemetry
from rs_server_common.utils.logging import Logging

# Add technical endpoints specific to the main application
technical_router = APIRouter(tags=["Technical"])


# include_in_schema=False: hide this endpoint from the swagger
@technical_router.get("/", include_in_schema=False)
async def home():
    """Home endpoint."""
    return {"message": "RS server home endpoint"}


# include_in_schema=False: hide this endpoint from the swagger
@technical_router.get("/health", response_model=HealthSchema, name="Check service health", include_in_schema=False)
async def health() -> HealthSchema:
    """
    Always return a flag set to 'true' when the service is up and running.
    \f
    Otherwise this code won't be run anyway and the caller will have other sorts of errors.
    """
    return HealthSchema(healthy=True)


@typing.no_type_check
def init_app(  # pylint: disable=too-many-locals
    api_version: str,
    routers: list[APIRouter],
    init_db: bool = True,
    pause: int = 3,
    timeout: int = None,
    startup_events: list[Callable] = None,
    shutdown_events: list[Callable] = None,
):  # pylint: disable=too-many-arguments
    """
    Init the FastAPI application.
    See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html

    Args:
        api_version (str): version of our application (not the version of the OpenAPI specification
        nor the version of FastAPI being used)
        routers (list[APIRouter]): list of FastAPI routers to add to the application.
        init_db (bool): should we init the database session ?
        timeout (int): timeout in seconds to wait for the database connection.
        pause (int): pause in seconds to wait for the database connection.
        startup_events (list[Callable]): list of functions that should be run before the application starts
        shutdown_events (list[Callable]): list of functions that should be run when the application is shutting down
    """

    logger = Logging.default(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Automatically executed when starting and stopping the FastAPI server."""

        ###########
        # STARTUP #
        ###########

        # Open database session. Loop until the connection works.
        if app.state.init_db:
            db_info = f"'{env['POSTGRES_USER']}@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}'"
            while True:
                try:
                    sessionmanager.open_session()
                    logger.info(f"Reached {env['POSTGRES_DB']!r} database on {db_info}")
                    break
                except sqlalchemy.exc.OperationalError:
                    logger.warning(f"Trying to reach {env['POSTGRES_DB']!r} database on {db_info}")

                    # Sleep for n seconds and raise exception if timeout is reached.
                    if app.state.pg_timeout is not None:
                        app.state.pg_timeout -= app.state.pg_pause
                        if app.state.pg_timeout < 0:
                            raise
                    await asyncio.sleep(app.state.pg_pause)

        # Init objects for dependency injection
        settings.set_http_client(httpx.AsyncClient())

        # Call additional startup events
        for event in app.state.startup_events:
            event()

        yield

        ############
        # SHUTDOWN #
        ############

        # Call additional shutdown events
        for event in app.state.shutdown_events:
            event()

        # Close objects for dependency injection
        await settings.del_http_client()

        # Close database session
        if app.state.init_db:
            try:
                await sessionmanager.close()
            except TypeError:  # TypeError: object NoneType can't be used in 'await' expression
                sessionmanager.close()

    # For cluster deployment: override the swagger /docs URL from an environment variable.
    # Also set the openapi.json URL under the same path.
    try:
        docs_url = env["RSPY_DOCS_URL"].strip("/")
        docs_params = {"docs_url": f"/{docs_url}", "openapi_url": f"/{docs_url}/openapi.json"}
    except KeyError:
        docs_params = {}

    # Init the FastAPI application
    app = FastAPI(title="RS-Server", version=api_version, lifespan=lifespan, **docs_params)

    # Configure OpenTelemetry
    opentelemetry.init_traces(app, settings.SERVICE_NAME)

    # Pass arguments to the app so they can be used in the lifespan function above.
    app.state.init_db = init_db
    app.state.pg_pause = pause
    app.state.pg_timeout = timeout
    app.state.startup_events = startup_events or []
    app.state.shutdown_events = shutdown_events or []

    # In cluster mode, add the api key security: the user must provide
    # an api key (generated from the apikey manager) to access the endpoints
    dependencies = []
    if settings.CLUSTER_MODE:
        dependencies.append(Depends(apikey_security))

    # Add the authenticated routers (and not the technical routers) to a single bigger router
    auth_router = APIRouter(dependencies=dependencies)
    for router in routers:
        auth_router.include_router(router)

    # Add routers to the FastAPI app
    app.include_router(auth_router)
    app.include_router(technical_router)

    return app
