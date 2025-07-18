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

from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

# Import the database table modules before initializing the FastAPI,
# that will init the database session and create the tables.
# pylint: disable=unused-import, import-outside-toplevel
# flake8: noqa
from rs_server_cadip import __version__
from rs_server_cadip.api.cadip_search import MockPgstacCadip
from rs_server_cadip.fastapi.cadip_routers import cadip_routers
from rs_server_common.fastapi_app import init_app
from rs_server_common.utils.error_handlers import register_stac_exception_handlers

# Used to supress stac_pydantic userwarnings related to serialization
warnings.filterwarnings("ignore", category=UserWarning, module="stac_pydantic")


def generate_openapi_schema():
    """."""
    if app.openapi_schema:
        return app.openapi_schema
    openapi_spec = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    app.openapi_schema = openapi_spec
    return app.openapi_schema


# Init the FastAPI application with the cadip routers.
app = init_app(__version__, cadip_routers, router_prefix="/cadip")

# Set properties for the cadip service
app.state.get_connection = MockPgstacCadip.get_connection
app.state.readpool = MockPgstacCadip.readpool()

register_stac_exception_handlers(app)


@app.get("/openapi.json", include_in_schema=False)
async def custom_openapi():
    """."""
    schema = generate_openapi_schema()
    return JSONResponse(content=schema, media_type="application/vnd.oai.openapi+json;version=3.0")
