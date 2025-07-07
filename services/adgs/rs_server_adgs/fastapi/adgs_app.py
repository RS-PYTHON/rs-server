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

import warnings
from http import HTTPStatus
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

# Import the database table modules before initializing the FastAPI,
# that will init the database session and create the tables.
# pylint: disable=unused-import, import-outside-toplevel
# flake8: noqa
from rs_server_adgs import __version__
from rs_server_adgs.api.adgs_search import MockPgstacAdgs
from rs_server_adgs.fastapi.adgs_routers import adgs_routers
from rs_server_common.fastapi_app import init_app

# Import STAC FastAPI error support
from stac_fastapi.api.errors import ErrorResponse, add_exception_handlers

# Used to supress stac_pydantic userwarnings related to serialization
warnings.filterwarnings("ignore", category=UserWarning, module="stac_pydantic")

# Init the FastAPI application with the adgs routers.
app = init_app(__version__, adgs_routers, router_prefix="/auxip")

# Set properties for the adgs service
app.state.get_connection = MockPgstacAdgs.get_connection
app.state.readpool = MockPgstacAdgs.readpool()

# Add domain exception handlers if any
add_exception_handlers(
    app,
    {
        # Add mappings like: MyCustomException: 400
        # Leave empty if not used yet
    },
)


@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    """Override HTTPException to return a STAC-style ErrorResponse."""
    # Convert status code to e.g. "NotFound", "BadRequest", etc.
    phrase = HTTPStatus(exc.status_code).phrase
    code = "".join(word.title() for word in phrase.split())

    # Return STAC-compliant error format
    payload: ErrorResponse = {
        "code": code,
        "description": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
    }
    return JSONResponse(status_code=exc.status_code, content=payload)
