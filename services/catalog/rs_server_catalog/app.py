# Copyright 2023-2026 Airbus, CS Group
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

"""RS-Server STAC catalog based on stac-fastapi-pgstac."""

import asyncio
import sys
from contextlib import asynccontextmanager
from os import environ as env
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Security
from fastapi.routing import APIRoute
from httpx._config import DEFAULT_TIMEOUT_CONFIG
from rs_server_catalog.data_management.data_lifecycle import DataLifecycle
from rs_server_catalog.middleware.catalog_middleware import CatalogMiddleware
from rs_server_catalog.utils import CATALOG_PREFIX
from rs_server_common import settings as common_settings
from rs_server_common.authentication.apikey import APIKEY_AUTH_HEADER
from rs_server_common.fastapi_app import flatten_routes
from rs_server_common.middlewares import (
    AuthenticationMiddleware,
    HandleExceptionsMiddleware,
    HealthMiddleware,
    PaginationLinksMiddleware,
    apply_middlewares,
    insert_middleware_after,
    insert_middleware_at,
)
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from stac_fastapi.pgstac.app import api
from stac_fastapi.pgstac.app import app as sfpg_app
from stac_fastapi.pgstac.app import with_transactions
from stac_fastapi.pgstac.db import close_db_connection, connect_to_db
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

logger = Logging.default(__name__)

# Technical endpoints (no authentication)
# NOTE: /_mgmt/health and /_mgmt/ping are actually handled by the HealthMiddleware
TECH_ENDPOINTS = ["/_mgmt/health", "/_mgmt/ping", "/api", "/api.html"]


def must_be_authenticated(route_path: str) -> bool:
    """Return true if a user must be authenticated to use this endpoint route path."""

    # Remove the /catalog prefix, if any
    path = route_path.removeprefix(CATALOG_PREFIX)

    no_auth = path in TECH_ENDPOINTS or path.startswith("/auth/")
    return not no_auth


def add_parameter_owner_id(parameters: list[dict]) -> list[dict]:
    """Add the owner id dictionnary to the parameter list.

    Args:
        parameters (list[dict]): the parameters list
        where we want to add the owner id parameter.
    Returns:
        dict: the new parameters list with the owner id parameter.
    """
    description = "Catalog owner id"
    to_add = {
        "description": description,
        "required": False,
        "schema": {"type": "string", "title": description, "description": description},
        "name": "owner_id",
        "in": "path",
    }
    parameters.append(to_add)
    return parameters


app: FastAPI = sfpg_app

# Add middlewares. When sending a request, the middleware order must be:
# Health -> CORS -> HandleExceptions -> Session -> Authentication -> [any other middlewares ...] -> Catalog
# Then after processing the request, the response is sent in the opposite order:
# Catalog -> [any other middlewares ...] -> Authentication -> Session -> HandleExceptions -> CORS -> Health

# Our custom middleware to process catalog endpoints is at the end
insert_middleware_at(app, len(app.user_middleware), Middleware(CatalogMiddleware))

# Middleware for implementing first and last buttons in STAC Browser
insert_middleware_after(
    app,
    CORSMiddleware,
    PaginationLinksMiddleware,
)

# Authentication verification
insert_middleware_after(
    app,
    CORSMiddleware,
    AuthenticationMiddleware,
    must_be_authenticated=must_be_authenticated,
)

# In cluster mode, add the oauth2 authentication and the SessionMiddleware
if common_settings.CLUSTER_MODE:
    app = apply_middlewares(app)

# Catch all exceptions and return a JSONResponse
insert_middleware_after(app, CORSMiddleware, HandleExceptionsMiddleware)
HandleExceptionsMiddleware.disable_default_exception_handler(app)

# More responsive /health and /ping endpoints
app.add_middleware(HealthMiddleware)

logger.debug(f"Middlewares: {app.user_middleware}")

# Data lifecycle management instance (cleaning of old assets)
lifecycle = DataLifecycle(app, api.client)


@asynccontextmanager
async def lifespan(my_app: FastAPI):
    """The lifespan function."""
    try:
        # Connect to the databse
        db_info = f"'{env['POSTGRES_USER']}@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}'"
        while True:
            try:
                await connect_to_db(my_app, add_write_connection_pool=with_transactions)
                logger.info("Reached %r database on %s", env["POSTGRES_DB"], db_info)
                break
            except ConnectionRefusedError:
                logger.warning("Trying to reach %r database on %s", env["POSTGRES_DB"], db_info)

                # timeout gestion if specified
                if my_app.state.pg_timeout is not None:
                    my_app.state.pg_timeout -= my_app.state.pg_pause
                    if my_app.state.pg_timeout < 0:
                        sys.exit("Unable to start up catalog service")
                await asyncio.sleep(my_app.state.pg_pause)

        common_settings.set_http_client(httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_CONFIG))

        # Run the data lifecycle management as an automatic periodic task
        lifecycle.run()

        yield

    finally:
        await lifecycle.cancel()
        await close_db_connection(my_app)
        await common_settings.del_http_client()


app.router.lifespan_context = lifespan

# Configure OpenTelemetry
init_opentelemetry.init_traces(app, "rs.server.catalog")


# In cluster mode, we add a FastAPI dependency to every authenticated endpoint so the lock icon (to enter an API key)
# can appear in the Swagger. This won't do the actual authentication, which is done by a FastAPI middleware.
# We do this because, in FastAPI, the dependencies are run after the middlewares, but here we need the
# authentication to work from inside the middlewares.
if common_settings.CLUSTER_MODE:

    async def just_for_the_lock_icon(
        apikey_value: Annotated[str, Security(APIKEY_AUTH_HEADER)] = "",  # pylint: disable=unused-argument
    ):
        """Dummy function to add a lock icon in Swagger to enter an API key."""

    # One scope for each Router path and method
    scopes = []
    for route in flatten_routes(api.app.router.routes):
        if not isinstance(route, APIRoute) or not must_be_authenticated(route.path):
            continue
        for method_ in route.methods:
            scopes.append({"path": route.path, "method": method_})

    api.add_route_dependencies(scopes=scopes, dependencies=[Depends(just_for_the_lock_icon)])

# Pause and timeout to connect to database (hardcoded for now)
app.state.pg_pause = 3  # seconds
app.state.pg_timeout = 30
