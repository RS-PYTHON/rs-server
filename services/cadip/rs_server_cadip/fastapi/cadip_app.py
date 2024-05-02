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

# Import the database table modules before initializing the FastAPI,
# that will init the database session and create the tables.
# pylint: disable=unused-import, import-outside-toplevel
# flake8: noqa
import rs_server_cadip.cadip_download_status  # DON'T REMOVE
from rs_server_cadip import __version__
from rs_server_cadip.fastapi.cadip_routers import cadip_routers
from rs_server_common.fastapi_app import init_app

# Init the FastAPI application with the cadip routers.
app = init_app(__version__, cadip_routers, init_db=True)
