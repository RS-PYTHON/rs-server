"""FastAPI application using PGStac.

Enables the extensions specified as a comma-delimited list in
the ENABLED_EXTENSIONS environment variable (e.g. `transactions,sort,query`).
If the variable is not set, enables all extensions.
"""

import os
from typing import Callable

from brotli_asgi import BrotliMiddleware
from fastapi import Depends, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import ORJSONResponse
from fastapi.routing import APIRoute
from rs_server_catalog.user_catalog import UserCatalogMiddleware
from rs_server_common import authentication
from rs_server_common.settings import local_mode
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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_403_FORBIDDEN

logger = Logging.default(__name__)


def add_parameter_owner_id(parameters: list[dict]) -> list[dict]:
    """Add the owner id dictionnary to the parameter list.

    Args:
        parameters (list[dict]): the parameters list
        where we want to add the owner id parameter.

    Returns:
        dict: the new parameters list with the owner id parameter.
    """
    to_add = {
        "description": "Catalog owner id",
        "required": True,
        "schema": {"type": "string", "title": "Catalog owner id", "description": "Catalog owner id"},
        "name": "owner_id",
        "in": "path",
    }
    parameters.append(to_add)
    return parameters


def extract_openapi_specification():
    """Extract the openapi specifications and modify the content to be conform
    to the rs catalog specifications. Then, apply the changes in the application.
    """
    if app.openapi_schema:
        return app.openapi_schema
    openapi_spec = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    openapi_spec_paths = openapi_spec["paths"]
    for key in openapi_spec_paths.keys():
        new_key = f"/catalog{key}" if key == "/search" else "/catalog/{owner_id}" + key
        openapi_spec_paths[new_key] = openapi_spec_paths.pop(key)
        endpoint = openapi_spec_paths[new_key]
        for method_key in endpoint.keys():
            method = endpoint[method_key]
            if new_key != "/catalog/search":
                method["parameters"] = add_parameter_owner_id(method.get("parameters", []))
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
        if (not local_mode()) and request.url.path.lower().startswith("/catalog"):
            # Read the api key passed in header
            apikey_value = request.headers.get(authentication.HEADER_NAME, None)
            if not apikey_value:
                raise HTTPException(status_code=HTTP_403_FORBIDDEN, detail="Not authenticated")

            # Check the api key validity, passed as an HTTP header.
            apikey_info = await authentication.apikey_security(request, apikey_value)

            # TODO: check api key rights before calling the next middleware
            logger.debug(f"API key information: {apikey_info}")

        # Call the next middleware
        return await call_next(request)


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
    ],
)
app = api.app
app.openapi = extract_openapi_specification


# In cluster mode, add the api key security dependency: the user must provide
# an api key (generated from the apikey manager) to access the endpoints
if not local_mode():
    # One scope for each ApiRouter path and method
    scopes = []
    for route in api.app.router.routes:
        if isinstance(route, APIRoute):
            for method_ in route.methods:
                scopes.append({"path": route.path, "method": method_})

    # Note: Depends(apikey_security) doesn't work (the function is not called) after we
    # changed the url prefixes in the openapi specification.
    # But this dependency still adds the lock icon in swagger to enter the api key.
    api.add_route_dependencies(scopes=scopes, dependencies=[Depends(authentication.apikey_security)])


@app.on_event("startup")
async def startup_event():
    """Connect to database on startup."""
    await connect_to_db(app)


@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection."""
    await close_db_connection(app)


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
