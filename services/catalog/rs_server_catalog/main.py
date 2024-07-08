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
import os
import sys
import traceback
from contextlib import asynccontextmanager
from os import environ as env
from typing import Any, Callable, Dict

import httpx
from brotli_asgi import BrotliMiddleware
from fastapi import Depends, FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, ORJSONResponse
from fastapi.routing import APIRoute
from rs_server_catalog import __version__
from rs_server_catalog.user_catalog import UserCatalog
from rs_server_common import authentication
from rs_server_common import settings as common_settings
from rs_server_common.utils import opentelemetry
from rs_server_common.utils.logging import Logging
from stac_fastapi.api.app import StacApi
from stac_fastapi.api.middleware import CORSMiddleware, ProxyHeaderMiddleware
from stac_fastapi.api.models import create_get_request_model, create_post_request_model
from stac_fastapi.extensions.core import (
    ContextExtension,
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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

logger = Logging.default(__name__)

# Technical endpoints (no authentication)
TECH_ENDPOINTS = ["/_mgmt/ping"]


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


def extract_openapi_specification():
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
    # add starlette routes
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
            if common_settings.CLUSTER_MODE and "api.html" not in route.path:
                to_add["security"] = [{"API key passed in HTTP header": []}]
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
                    if (
                        new_key not in ["/catalog/search", "/catalog/", "/catalog/collections"]
                        and "parameters" in method
                    ):
                        method["parameters"] = add_parameter_owner_id(method.get("parameters", []))
                    elif (
                        "operationId" in method
                        and isinstance(method["operationId"], str)
                        and method["operationId"] == "Search_search_get"
                    ):
                        method["description"] = (
                            "Endpoint /catalog/search. The filter-lang parameter is cql2-text by default."
                        )
    owner_id = "Owner ID"
    catalog_owner_id: Dict[str, Any] = {
        "get": {
            "summary": "Landing page for the catalog owner id only.",
            "description": "Endpoint.",
            "operationId": "Get_landing_page_owner_id",
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
            ],
        },
    }
    path = "/catalog/catalogs/{owner_id}"
    method = "GET"
    if common_settings.CLUSTER_MODE:
        catalog_owner_id["security"] = [{"API key passed in HTTP header": []}]
    openapi_spec["paths"].setdefault(path, {})[method.lower()] = catalog_owner_id
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
    "context": ContextExtension(),
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

        # Only in cluster mode (not local mode) and for the catalog endpoints
        if (
            (common_settings.CLUSTER_MODE)
            and request.url.path.startswith("/catalog")
            and request.url.path != "/catalog/api.html"
        ):

            # Check the api key validity, passed in HTTP header
            await authentication.apikey_security(
                request=request,
                apikey_header=request.headers.get(authentication.APIKEY_HEADER, None),
            )

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

        # NOTE: the same 'self' instance is reused by all requests so it must
        # not be used by several requests at the same time or we'll have conflicts.
        # Do everything in a specific object.
        return await UserCatalog(client).dispatch(request, call_next)


api = StacApi(
    settings=settings,
    extensions=extensions,
    client=CoreCrudClient(post_request_model=post_request_model),
    response_class=ORJSONResponse,
    search_get_request_model=create_get_request_model(extensions),
    search_post_request_model=post_request_model,
    middlewares=[
        UserCatalogMiddleware,
        BrotliMiddleware,
        CORSMiddleware,
        ProxyHeaderMiddleware,
        AuthenticationMiddleware,
        DontRaiseExceptions,
    ],
)
app = api.app
app.openapi = extract_openapi_specification


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

        common_settings.set_http_client(httpx.AsyncClient())

        yield

    finally:
        await close_db_connection(my_app)

        await common_settings.del_http_client()


app.router.lifespan_context = lifespan

# Configure OpenTelemetry
opentelemetry.init_traces(app, "rs.server.catalog")

# In cluster mode, add the api key security dependency: the user must provide
# an api key (generated from the apikey manager) to access the endpoints
if common_settings.CLUSTER_MODE:
    # One scope for each ApiRouter path and method
    scopes = []
    for route in api.app.router.routes:
        if isinstance(route, APIRoute):
            # Not on the technical endpoints
            if route.path in TECH_ENDPOINTS:
                continue
            for method_ in route.methods:
                scopes.append({"path": route.path, "method": method_})

    # Note: Depends(apikey_security) doesn't work (the function is not called) after we
    # changed the url prefixes in the openapi specification.
    # But this dependency still adds the lock icon in swagger to enter the api key.
    api.add_route_dependencies(scopes=scopes, dependencies=[Depends(authentication.apikey_security)])

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
