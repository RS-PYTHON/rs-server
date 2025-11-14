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

"""Init a root FastAPI application from all the sub-project routers."""

import os

from fastapi import APIRouter, FastAPI, Request
from rs_server_adgs.api.adgs_search import MockPgstacAdgs
from rs_server_adgs.fastapi.adgs_routers import adgs_routers
from rs_server_cadip.api.cadip_search import MockPgstacCadip
from rs_server_cadip.fastapi.cadip_routers import cadip_routers
from rs_server_common.authentication.oauth2 import SWAGGER_HOMEPAGE
from rs_server_common.fastapi_app import init_app as init_app_with_args
from rs_server_common.stac_api_common import MockPgstac
from rs_server_common.utils.error_handlers import register_stac_exception_handlers
from rs_server_prip.api.prip_search import MockPgstacPrip
from rs_server_prip.fastapi.prip_routers import prip_routers

ROUTER_PREFIX_AUXIP = {"router_prefix": "/auxip"}
ROUTER_PREFIX_CADIP = {"router_prefix": "/cadip"}
ROUTER_PREFIX_PRIP = {"router_prefix": "/prip"}


class MockPgstacTest(MockPgstac):
    """Implementation of MockPgstac that returns an adgs or cadip instance, depending on the request."""

    def __new__(cls, request: Request | None = None, *args, **kwargs):  # pylint: disable=keyword-arg-before-vararg
        """Init a child implementation."""
        router_prefix = os.getenv("router_prefix")
        endpoint = request.url.path if request else ""
        if (router_prefix == "/auxip") or endpoint.startswith(("/adgs", "/auxip")):
            return MockPgstacAdgs(request, *args, **kwargs)
        if (router_prefix == "/prip") or endpoint.startswith("/prip"):
            return MockPgstacPrip(request, *args, **kwargs)
        if (router_prefix == "/cadip") or endpoint.startswith("/cadip"):
            return MockPgstacCadip(request, *args, **kwargs)
        raise RuntimeError(f"Invalid router_prefix or endpoint: {router_prefix!r} / {endpoint!r}")


def swagger_router() -> APIRouter:
    """Returns a router simulating the frontend swagger page to make oauth2 tests work"""
    router = APIRouter(tags=["Swagger"])

    @router.get(SWAGGER_HOMEPAGE)
    async def get_docs():
        """Endpoint must exist for oauth2 tests to work"""
        return ""

    return router


def init_app(router_prefix: str = "") -> FastAPI:
    """Run all routers for the tests."""
    routers = adgs_routers + cadip_routers + prip_routers + [swagger_router()]
    app: FastAPI = init_app_with_args(
        api_version="test",
        routers=routers,
        router_prefix=router_prefix,
    )
    register_stac_exception_handlers(app)
    app.state.get_connection = MockPgstacTest.get_connection
    app.state.readpool = MockPgstacTest.readpool()
    return app
