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

"""FastAPI application using PGStac.

Enables the extensions specified as a comma-delimited list in
the ENABLED_EXTENSIONS environment variable (e.g. `transactions,sort,query`).
If the variable is not set, enables all extensions.
"""
import asyncio
import copy
import os
import sys
import traceback
from contextlib import asynccontextmanager
from os import environ as env
from typing import Annotated, Any, Callable, Dict

import httpx
from brotli_asgi import BrotliMiddleware
from fastapi import Depends, FastAPI, Request, Security
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, ORJSONResponse
from fastapi.routing import APIRoute
from httpx._config import DEFAULT_TIMEOUT_CONFIG
from rs_server_catalog import __version__
from rs_server_catalog.user_catalog import UserCatalog
from rs_server_common import settings as common_settings
from rs_server_common.authentication import authentication, oauth2
from rs_server_common.authentication.apikey import (
    APIKEY_AUTH_HEADER,
    APIKEY_HEADER,
    APIKEY_SCHEME_NAME,
)
from rs_server_common.authentication.oauth2 import AUTH_PREFIX, LoginAndRedirect
from rs_server_common.utils import opentelemetry
from rs_server_common.utils.logging import Logging
from stac_fastapi.api.app import StacApi
from stac_fastapi.api.middleware import CORSMiddleware, ProxyHeaderMiddleware
from stac_fastapi.api.models import (
    ItemCollectionUri,
    create_get_request_model,
    create_post_request_model,
    create_request_model,
)
from stac_fastapi.extensions.core import (  # pylint: disable=no-name-in-module
    FieldsExtension,
    FilterExtension,
    SortExtension,
    TokenPaginationExtension,
    TransactionExtension,
)
from stac_fastapi.extensions.third_party import BulkTransactionExtension
from stac_fastapi.pgstac.config import Settings
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.pgstac.db import close_db_connection, connect_to_db
from stac_fastapi.pgstac.extensions import QueryExtension
from stac_fastapi.pgstac.extensions.filter import FiltersClient
from stac_fastapi.pgstac.transactions import BulkTransactionsClient, TransactionsClient
from stac_fastapi.pgstac.types.search import PgstacSearch
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.routing import Route
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

logger = Logging.default(__name__)

# Technical endpoints (no authentication)
TECH_ENDPOINTS = ["/_mgmt/ping"]


def must_be_authenticated(route_path: str) -> bool:
    """Return true if a user must be authenticated to use this endpoint route path."""

    # Remove the /catalog prefix, if any
    path = route_path.removeprefix("/catalog")

    no_auth = (path in TECH_ENDPOINTS) or (path in ["/api", "/api.html", "/health"]) or path.startswith("/auth/")
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


def get_new_key(original_key: str) -> str:  # pylint: disable=missing-function-docstring
    """For all existing endpoints, add prefix and owner_id parameter."""
    res = ""
    match original_key:
        case "/":
            res = "/catalog/"
        case "/collections":
            res = "/catalog/collections"
        case "/collections/{collection_id}":
            res = "/catalog/collections/{owner_id}:{collection_id}"
        case "/collections/{collection_id}/items":
            res = "/catalog/collections/{owner_id}:{collection_id}/items"
        case "/collections/{collection_id}/items/{item_id}":
            res = "/catalog/collections/{owner_id}:{collection_id}/items/{item_id}"
        case "/search":
            res = "/catalog/search"
        case "/queryables":
            res = "/catalog/queryables"
        case "/collections/{collection_id}/queryables":
            res = "/catalog/collections/{owner_id}:{collection_id}/queryables"
        case "/collections/{collection_id}/bulk_items":
            res = "/catalog/collections/{owner_id}:{collection_id}/bulk_items"
        case "/conformance":
            res = "/catalog/conformance"
    return res


def extract_openapi_specification():  # pylint: disable=too-many-locals
    """Extract the openapi specifications and modify the content to be conform
    to the rs catalog specifications. Then, apply the changes in the application.
    """
    if app.openapi_schema:
        return app.openapi_schema
    openapi_spec = get_openapi(
        title=app.title,
        version=__version__,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    # add starlette routes: /api, /api.html and /docs/oauth2-redirect and add /catalog prefix
    for route in app.routes:  # pylint: disable=redefined-outer-name
        if isinstance(route, Route) and route.path in ["/api", "/api.html", "/docs/oauth2-redirect"]:
            path = f"/catalog{route.path}"
            method = "GET"
            to_add = {
                "summary": f"Auto-generated {method} for {path}",
                "responses": {
                    "200": {
                        "description": "Successful Response",
                        "content": {"application/json": {"example": {"message": "Success"}}},
                    },
                },
                "operationId": "/catalog" + route.operation_id if hasattr(route, "operation_id") else route.path,
            }
            if common_settings.CLUSTER_MODE and must_be_authenticated(route.path):
                to_add["security"] = [{APIKEY_SCHEME_NAME: []}]
            openapi_spec["paths"].setdefault(path, {})[method.lower()] = to_add

    openapi_spec_paths = openapi_spec["paths"]
    for key in list(openapi_spec_paths.keys()):
        if key in TECH_ENDPOINTS:
            del openapi_spec_paths[key]
            continue

        new_key = get_new_key(key)
        if new_key:
            openapi_spec_paths[new_key] = openapi_spec_paths.pop(key)
            endpoint = openapi_spec_paths[new_key]
            for method_key in endpoint.keys():
                method = endpoint[method_key]
                if isinstance(method, dict):
                    if (  # Add the parameter owner_id in the endpoint if needed.
                        new_key not in ["/catalog/search", "/catalog/", "/catalog/collections"]
                        and "parameters" in method
                    ):
                        method["parameters"] = add_parameter_owner_id(method.get("parameters", []))
                    elif (  # Add description to the /catalog/search endpoint.
                        "operationId" in method
                        and isinstance(method["operationId"], str)
                        and method["operationId"] == "Search_search_get"
                    ):
                        method["description"] = (
                            "Endpoint /catalog/search. The filter-lang parameter is cql2-text by default."
                        )
    # Create the endpoint /catalog/catalogs/owner_id
    owner_id = "Owner ID"
    collection_id = "Collection ID"

    # Create the endpoint /catalog/collections/{owner_id}:{collection_id}/search. GET METHOD
    # We copy the parameters from the original /catalog/search endpoint and we add new parameters.
    search_parameters = copy.deepcopy(openapi_spec["paths"]["/catalog/search"]["get"]["parameters"])
    catalog_collection_search: Dict[str, Any] = {
        "summary": "search endpoint to search only inside a specific collection.",
        "description": "Endpoint.",
        "operationId": "Get_search_collection",
        "responses": {
            "200": {"description": "Successful Response", "content": {"application/json": {"schema": {}}}},
        },
        "parameters": [
            {
                "description": owner_id,
                "required": True,
                "schema": {"type": "string", "title": owner_id, "description": owner_id},
                "name": "owner_id",
                "in": "path",
            },
            {
                "description": collection_id,
                "required": True,
                "schema": {"type": "string", "title": collection_id, "description": collection_id},
                "name": "collection_id",
                "in": "path",
            },
        ],
    }
    catalog_collection_search["parameters"].extend(search_parameters)
    catalog_collection_search_path = "/catalog/collections/{owner_id}:{collection_id}/search"

    # Create the endpoint /catalog/collections/{owner_id}:{collection_id}/search. POST METHOD
    catalog_collection_search_post: Dict[str, Any] = {
        "summary": "search endpoint to search only inside a specific collection.",
        "description": "Endpoint.",
        "operationId": "Post_search_collection",
        "responses": {
            "200": {"description": "Successful Response", "content": {"application/geojson": {"schema": {}}}},
        },
    }

    # Add security parameters.
    if common_settings.CLUSTER_MODE:
        catalog_collection_search["security"] = [{APIKEY_SCHEME_NAME: []}]
        catalog_collection_search_post["security"] = [{APIKEY_SCHEME_NAME: []}]
    # Add all previous created endpoints.
    openapi_spec["paths"][catalog_collection_search_path] = {"get": catalog_collection_search}
    openapi_spec["paths"][catalog_collection_search_path]["post"] = catalog_collection_search_post
    app.openapi_schema = openapi_spec
    return app.openapi_schema


settings = Settings()
extensions_map = {
    "transaction": TransactionExtension(
        client=TransactionsClient(),
        settings=settings,
        response_class=ORJSONResponse,
    ),
    "query": QueryExtension(),
    "sort": SortExtension(),
    "fields": FieldsExtension(),
    "pagination": TokenPaginationExtension(),
    "filter": FilterExtension(client=FiltersClient()),
    "bulk_transactions": BulkTransactionExtension(client=BulkTransactionsClient()),
}

if enabled_extensions := os.getenv("ENABLED_EXTENSIONS"):
    extensions = [extensions_map[extension_name] for extension_name in enabled_extensions.split(",")]
else:
    extensions = list(extensions_map.values())

post_request_model = create_post_request_model(extensions, base_model=PgstacSearch)


class AuthenticationMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """
    Implement authentication verification.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        """
        Middleware implementation.
        """

        if common_settings.CLUSTER_MODE and must_be_authenticated(request.url.path):
            try:
                # Check the api key validity, passed in HTTP header, or oauth2 autentication (keycloak)
                await authentication.authenticate(
                    request=request,
                    apikey_value=request.headers.get(APIKEY_HEADER, None),
                )

            # Login and redirect to the calling endpoint.
            except LoginAndRedirect:
                return await oauth2.login(request)

        # Call the next middleware
        return await call_next(request)


class DontRaiseExceptions(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """
    In FastAPI we can raise HttpExceptions in the middle of the python code, instead of returning a JSONResponse.
    But that doesn't work well in the middlewares: a response with error 500 is returned instead of the
    original HttpException status code. So we handle this by making the conversion manually.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        """
        Middleware implementation.
        """

        try:
            return await call_next(request)  # Call the next middleware
        except Exception as exception:  # pylint: disable=broad-exception-caught

            # Print the error with the stacktrace in the log
            logger.error(traceback.format_exc())

            # Get the status code and content from the HTTPException
            if isinstance(exception, StarletteHTTPException):
                status_code = exception.status_code
                content = exception.detail

            # Else use a generic status code, and content = exception message
            else:
                status_code = HTTP_500_INTERNAL_SERVER_ERROR
                content = repr(exception)

            return JSONResponse(status_code=status_code, content=content)


client = CoreCrudClient(post_request_model=post_request_model)


class UserCatalogMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """The user catalog middleware."""

    async def dispatch(self, request, call_next):
        """Redirect the user catalog specific endpoint and adapt the response content."""
        response = await UserCatalog(client).dispatch(request, call_next)
        return response


items_get_request_model = create_request_model(
    "ItemCollectionURI",
    base_model=ItemCollectionUri,
    mixins=[TokenPaginationExtension().GET],
)

api = StacApi(
    settings=settings,
    extensions=extensions,
    items_get_request_model=items_get_request_model,
    client=CoreCrudClient(post_request_model=post_request_model),
    response_class=ORJSONResponse,
    search_get_request_model=create_get_request_model(extensions),
    search_post_request_model=post_request_model,
    middlewares=[
        Middleware(UserCatalogMiddleware),
        Middleware(BrotliMiddleware),
        Middleware(ProxyHeaderMiddleware),
        Middleware(AuthenticationMiddleware),
        Middleware(DontRaiseExceptions),
        Middleware(
            CORSMiddleware,  # WARNING: must be last !
            allow_origins=common_settings.STAC_BROWSER_URLS,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        ),
    ],
)
app = api.app
app.openapi = extract_openapi_specification

# In cluster mode, add the oauth2 authentication
if common_settings.CLUSTER_MODE:

    # Existing middlewares
    middleware_names = [middleware.cls.__name__ for middleware in app.user_middleware]

    # Insert the SessionMiddleware (to save cookies) after the DontRaiseExceptions middleware.
    # Code copy/pasted from app.add_middleware(SessionMiddleware, secret_key=cookie_secret)
    if app.middleware_stack:
        raise RuntimeError("Cannot add middleware after an application has started")
    middleare_index = middleware_names.index("DontRaiseExceptions")
    cookie_secret = os.environ["RSPY_COOKIE_SECRET"]
    app.user_middleware.insert(middleare_index + 1, Middleware(SessionMiddleware, secret_key=cookie_secret))

    # Get the oauth2 router
    oauth2_router = oauth2.get_router(app)

    # Add it to the FastAPI application
    app.include_router(
        oauth2_router,
        tags=["Authentication"],
        prefix=AUTH_PREFIX,
        include_in_schema=True,
    )


@asynccontextmanager
async def lifespan(my_app: FastAPI):
    """The lifespan function."""
    try:
        # Connect to the databse
        db_info = f"'{env['POSTGRES_USER']}@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}'"
        while True:
            try:
                await connect_to_db(my_app)
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

        yield

    finally:
        await close_db_connection(my_app)

        await common_settings.del_http_client()


app.router.lifespan_context = lifespan

# Configure OpenTelemetry
opentelemetry.init_traces(app, "rs.server.catalog")


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
    for route in api.app.router.routes:
        if not isinstance(route, APIRoute) or not must_be_authenticated(route.path):
            continue
        for method_ in route.methods:
            scopes.append({"path": route.path, "method": method_})

    api.add_route_dependencies(scopes=scopes, dependencies=[Depends(just_for_the_lock_icon)])

# Pause and timeout to connect to database (hardcoded for now)
app.state.pg_pause = 3  # seconds
app.state.pg_timeout = 30


def run():
    """Run app from command line using uvicorn if available."""
    try:
        import uvicorn  # pylint: disable=import-outside-toplevel

        uvicorn.run(
            "rs_server_catalog.main:app",
            host=settings.app_host,
            port=settings.app_port,
            log_level="info",
            reload=settings.reload,
            root_path=os.getenv("UVICORN_ROOT_PATH", ""),
        )
    except ImportError:
        raise RuntimeError("Uvicorn must be installed in order to use command")  # pylint: disable=raise-missing-from


if __name__ == "__main__":
    run()
