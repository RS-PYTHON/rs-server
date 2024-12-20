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

import httpx
import sqlalchemy
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from httpx._config import DEFAULT_TIMEOUT_CONFIG
from rs_server_common import settings
from rs_server_common.authentication import oauth2
from rs_server_common.authentication.authentication import authenticate
from rs_server_common.authentication.authentication_to_external import (
    init_rs_server_config_yaml,
)
from rs_server_common.authentication.oauth2 import AUTH_PREFIX
from rs_server_common.db.database import sessionmanager
from rs_server_common.schemas.health_schema import HealthSchema
from rs_server_common.utils import opentelemetry
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import DontRaiseExceptions
from stac_fastapi.api.app import StacApi
from stac_fastapi.api.middleware import ProxyHeaderMiddleware
from stac_fastapi.api.models import create_get_request_model, create_post_request_model
from stac_fastapi.api.routes import add_route_dependencies
from stac_fastapi.extensions.core import (
    FieldsExtension,
    FilterExtension,
    PaginationExtension,
    SortExtension,
)
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.pgstac.extensions import QueryExtension
from stac_fastapi.pgstac.extensions.filter import FiltersClient
from stac_fastapi.pgstac.types.search import PgstacSearch
from starlette.datastructures import State

# Add technical endpoints specific to the main application
technical_router = APIRouter(tags=["Technical"])


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
def init_app(  # pylint: disable=too-many-locals, too-many-statements
    api_version: str,
    routers: list[APIRouter],
    init_db: bool = True,
    pause: int = 3,
    timeout: int = None,
    router_prefix: str = "",
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
        router_prefix (str): used by stac_fastapi
    """

    logger = Logging.default(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Automatically executed when starting and stopping the FastAPI server."""

        ###########
        # STARTUP #
        ###########

        # Init the rs-server configuration file for authentication to extenal stations
        init_rs_server_config_yaml()

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
        settings.set_http_client(httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_CONFIG))

        yield

        ############
        # SHUTDOWN #
        ############

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

    # Init a pgstac client for adgs and cadip.
    # TODO: remove this when adgs and cadip switch to a stac_fastapi application.
    # Example taken from: https://github.com/stac-utils/stac-fastapi-pgstac/blob/main/tests/api/test_api.py
    app.state.router_prefix = router_prefix  # NOTE: maybe we should keep this one
    extensions = [  # no transactions because we don't update the database
        # TransactionExtension(client=TransactionsClient(), settings=api_settings),
        QueryExtension(),
        SortExtension(),
        FieldsExtension(),
        FilterExtension(client=FiltersClient()),
        PaginationExtension(),
        # BulkTransactionExtension(client=BulkTransactionsClient()),
    ]
    search_post_request_model = create_post_request_model(extensions, base_model=PgstacSearch)
    app.state.pgstac_client = CoreCrudClient(post_request_model=search_post_request_model)

    # TODO: remove this when adgs and cadip switch to a stac_fastapi application.
    app.state.pgstac_client.extensions = extensions
    for ext in extensions:
        ext.register(app)
    app.state.pgstac_client.title = app.title
    app.state.pgstac_client.description = app.description
    # Implement the /search endpoints by simulating a StacApi object, TODO remove this also
    app.settings = State()
    app.settings.enable_response_models = False
    app.settings.use_api_hydrate = False
    app.state.settings = app.settings
    app.client = app.state.pgstac_client
    app.search_get_request_model = create_get_request_model(extensions)
    app.search_post_request_model = search_post_request_model
    app.router.prefix = router_prefix  # TODO should be used by other endpoints ?
    StacApi.register_get_search(app)
    StacApi.register_post_search(app)
    app.router.prefix = ""
    if settings.CLUSTER_MODE:
        scopes = []  # One scope for each Router path and method
        for route in app.router.routes:
            if not isinstance(route, APIRoute):
                continue
            for method_ in route.methods:
                scopes.append({"path": route.path, "method": method_})
        add_route_dependencies(app.router.routes, scopes=scopes, dependencies=[Depends(authenticate)])
    # TODO: title and description must be set using the env vars
    # CATALOG_METADATA_TITLE and CATALOG_METADATA_DESCRIPTION
    service = router_prefix.strip("/").title()
    app.state.pgstac_client.title = f"RS-PYTHON {service} collections"
    app.state.pgstac_client.description = f"{service} collections of Copernicus Reference System Python"

    dependencies = []
    if settings.CLUSTER_MODE:

        # Get the oauth2 router
        oauth2_router = oauth2.get_router(app)

        # Add it to the FastAPI application
        app.include_router(
            oauth2_router,
            tags=["Authentication"],
            prefix=AUTH_PREFIX,
            include_in_schema=True,
        )

        # Add the api key / oauth2 security: the user must provide
        # an api key (generated from the apikey manager) or authenticate to the
        # oauth2 service (keycloak) to access the endpoints
        dependencies.append(Depends(authenticate))

    # Add all the input routers (and not the oauth2 nor technical routers) to a single bigger router
    # to which we add the authentication dependency.
    need_auth_router = APIRouter(dependencies=dependencies)
    for router in routers:
        need_auth_router.include_router(router)

    # Add routers to the FastAPI app
    app.include_router(need_auth_router)
    app.include_router(technical_router)

    # Catch all exceptions and return a JSONResponse
    app.add_middleware(DontRaiseExceptions)

    # This middleware allows to have consistant http/https protocol in stac links
    app.add_middleware(ProxyHeaderMiddleware)

    # Add CORS requests from the STAC browser
    if settings.STAC_BROWSER_URLS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.STAC_BROWSER_URLS,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        )

    return app
