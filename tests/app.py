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

from fastapi import Request
from rs_server_adgs.api.adgs_search import MockPgstacAdgs
from rs_server_adgs.fastapi.adgs_routers import adgs_routers
from rs_server_cadip.api.cadip_search import MockPgstacCadip
from rs_server_cadip.fastapi.cadip_routers import cadip_routers
from rs_server_common.fastapi_app import init_app as init_app_with_args
from rs_server_common.stac_api_common import MockPgstac


class MockPgstacTest(MockPgstac):
    """Implementation of MockPgstac that returns an adgs or cadip instance, depending on the request."""

    def __new__(cls, request: Request | None = None, *args, **kwargs):
        """Init a child implementation."""
        router_prefix = os.getenv("router_prefix")
        endpoint = request.url.path if request else ""
        if (router_prefix == "/auxip") or endpoint.startswith(("/adgs", "/auxip")):
            return MockPgstacAdgs(request, *args, **kwargs)
        if (router_prefix == "/cadip") or endpoint.startswith("/cadip"):
            return MockPgstacCadip(request, *args, **kwargs)
        raise RuntimeError(f"Invalid router_prefix or endpoint: {router_prefix!r} / {endpoint!r}")


def init_app(router_prefix: str = ""):
    """Run all routers for the tests."""
    routers = adgs_routers + cadip_routers
    app = init_app_with_args(
        api_version="test",
        routers=routers,
        init_db=True,
        pause=3,
        timeout=6,
        router_prefix=router_prefix,
    )
    app.state.get_connection = MockPgstacTest.get_connection
    app.state.readpool = MockPgstacTest.readpool()
    return app
