"""FastAPI application using PGStac.

Enables the extensions specified as a comma-delimited list in
the ENABLED_EXTENSIONS environment variable (e.g. `transactions,sort,query`).
If the variable is not set, enables all extensions.
"""

import os
import json
from pathlib import Path
from fastapi.openapi.utils import get_openapi

from brotli_asgi import BrotliMiddleware
from fastapi.responses import ORJSONResponse
from stac_fastapi.api.app import StacApi
from stac_fastapi.api.middleware import ProxyHeaderMiddleware, CORSMiddleware
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

from rs_server_catalog.user_catalog import UserCatalogMiddleware


def add_parameter_owner_id(parameters: list[dict]) -> dict:
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


def extract_openapi_specification() -> None:
    """Extract the openapi specifications and modify the content to be conform
    to the rs catalog specifications. Then, apply the changes in the application.
    """
    openapi_spec = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    openapi_spec_paths = openapi_spec["paths"]
    for key, _ in openapi_spec_paths.items():
        new_key = "/catalog/{owner_id}" + key
        openapi_spec_paths[new_key] = openapi_spec_paths.pop(key)
        endpoint = openapi_spec_paths[new_key]
        for method_key, _ in endpoint.items():
            method = endpoint[method_key]
            if "parameters" in method.keys():
                method["parameters"] = add_parameter_owner_id(method["parameters"])
            else:
                method["parameters"] = add_parameter_owner_id([])
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

api = StacApi(
    settings=settings,
    extensions=extensions,
    client=CoreCrudClient(post_request_model=post_request_model),
    response_class=ORJSONResponse,
    search_get_request_model=create_get_request_model(extensions),
    search_post_request_model=post_request_model,
    middlewares=[UserCatalogMiddleware, BrotliMiddleware, CORSMiddleware, ProxyHeaderMiddleware],
)
app = api.app
app.openapi_schema = extract_openapi_specification()


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
        import uvicorn

        uvicorn.run(
            "stac_fastapi.pgstac.app:app",
            host=settings.app_host,
            port=settings.app_port,
            log_level="info",
            reload=settings.reload,
            root_path=os.getenv("UVICORN_ROOT_PATH", ""),
        )
    except ImportError:
        raise RuntimeError("Uvicorn must be installed in order to use command")


if __name__ == "__main__":
    run()


def create_handler(app):
    """Create a handler to use with AWS Lambda if mangum available."""
    try:
        from mangum import Mangum

        return Mangum(app)
    except ImportError:
        return None


handler = create_handler(app)
