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

"""Module used to configure pytests."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(name="staging_client")
def client_():
    """set pygeoapi env variables and init fastapi client app."""
    # To be updated
    geoapi_cfg = Path("rs_server_staging/config/config.yml").absolute()
    openapi_json = Path("rs_server_staging/config/openapi.json").absolute()
    #
    os.environ["PYGEOAPI_CONFIG"] = str(geoapi_cfg)
    os.environ["PYGEOAPI_OPENAPI"] = str(openapi_json)
    from ..rs_server_staging.main import app  # pylint: disable=import-outside-toplevel

    # Test the FastAPI application, opens the database session
    with TestClient(app) as client:
        yield client
