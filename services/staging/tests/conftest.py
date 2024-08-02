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

# Ignore not-at-top level import errors

# pylint: disable=C0413
# flake8: noqa: F402

import os
import os.path as osp
from pathlib import Path

# set pygeoapi env variables
geoapi_cfg = Path(osp.realpath(osp.dirname(__file__))) / "resources" / "test_config.yml"
os.environ["PYGEOAPI_CONFIG"] = str(geoapi_cfg)
os.environ["PYGEOAPI_OPENAPI"] = ""

import pytest
from fastapi.testclient import TestClient
from rs_server_staging.main import app  # pylint: disable=import-error


@pytest.fixture(name="staging_client")
def client_():
    """init fastapi client app."""
    # Test the FastAPI application, opens the database session
    with TestClient(app) as client:
        yield client
