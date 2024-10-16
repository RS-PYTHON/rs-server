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

"""
stac-fastapi-pgstac service for Cadip, mainly taken from
https://github.com/stac-utils/stac-fastapi-pgstac/blob/main/tests/api/test_api.py
"""

import logging
import os
from contextlib import asynccontextmanager


from rs_server_common import settings as common_settings
import uvicorn
from fastapi import APIRouter, FastAPI
from starlette.responses import Response
from fastapi.middleware import Middleware
from fastapi.responses import ORJSONResponse
from stac_fastapi.api.app import StacApi
from stac_fastapi.api.middleware import CORSMiddleware
from stac_fastapi.api.models import (
    ItemCollectionUri,
    create_get_request_model,
    create_post_request_model,
    create_request_model,
)
from stac_fastapi.extensions.core import (
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
from starlette.requests import Request
import typing

async def dispatch(request: Request, call_next:typing.Callable[[Request], typing.Awaitable[Response]]) -> Response:
    """Custom endpoints implementation"""
    print(f"\n\n{request.url.path}\n\n")
    response = await call_next(request)
    return response

use_api_hydrate = False
enable_response_models = False
testing = False
prefix = ""

# Init the settings to connect to the postgres database.
# In our case we don't use this database so set the db fields to None.
api_settings = Settings(
    postgres_user=None,
    postgres_pass=None,
    postgres_host_reader=None,
    postgres_host_writer=None,
    postgres_port=None,
    postgres_dbname=None,
    app_host=None,
    app_port=None,
    use_api_hydrate=use_api_hydrate,
    enable_response_models=enable_response_models,
    testing=testing,
)

api_settings.openapi_url = prefix + api_settings.openapi_url
api_settings.docs_url = prefix + api_settings.docs_url

extensions = [
    # TransactionExtension(client=TransactionsClient(), settings=api_settings),
    QueryExtension(),
    SortExtension(),
    FieldsExtension(),
    TokenPaginationExtension(),
    FilterExtension(client=FiltersClient()),
    # BulkTransactionExtension(client=BulkTransactionsClient()),
]

items_get_request_model = create_request_model(
    model_name="ItemCollectionUri",
    base_model=ItemCollectionUri,
    mixins=[
        TokenPaginationExtension().GET,
        FilterExtension(client=FiltersClient()).GET,
    ],
    request_type="GET",
)
search_get_request_model = create_get_request_model(extensions)
search_post_request_model = create_post_request_model(
    extensions, base_model=PgstacSearch
)
api = StacApi(
    settings=api_settings,
    extensions=extensions,
    client=CoreCrudClient(post_request_model=search_post_request_model),
    items_get_request_model=items_get_request_model,
    search_get_request_model=search_get_request_model,
    search_post_request_model=search_post_request_model,
    response_class=ORJSONResponse,
    router=APIRouter(prefix=prefix),
    middlewares=[
        Middleware(BaseHTTPMiddleware, dispatch=dispatch),
        # Middleware(AuthorizationMiddleware),
        # Middleware(LoginMiddleware),
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # await connect_to_db(app)
    yield
    # await close_db_connection(app)


app.router.lifespan_context = lifespan

if __name__ == "__main__":
    uvicorn.run(
        "rs_server_cadip.stac_service_cadip:app",
        host=api_settings.app_host,
        port=api_settings.app_port,
        log_level="info",
        reload=api_settings.reload,
    )

# NOTE: you can open your STAC catalog Swagger page under http://localhost:9999/api.html
