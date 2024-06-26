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

from rs_server_adgs.fastapi.adgs_routers import adgs_routers
from rs_server_cadip.fastapi.cadip_routers import cadip_routers
from rs_server_common.fastapi_app import init_app as init_app_with_args


def init_app():
    """Run all routers for the tests."""
    routers = adgs_routers + cadip_routers
    return init_app_with_args(
        api_version="test",
        routers=routers,
        init_db=True,
        pause=3,
        timeout=6,
    )
