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

import asyncio
import os
import os.path as osp
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from rs_server_staging.processors import Staging

os.environ["RSPY_LOCAL_MODE"] = "1"
# set pygeoapi env variables
geoapi_cfg = Path(osp.realpath(osp.dirname(__file__))) / "resources" / "test_config.yml"
os.environ["PYGEOAPI_CONFIG"] = str(geoapi_cfg)
os.environ["PYGEOAPI_OPENAPI"] = ""
TEST_DETAIL = "Test detail"

from rs_server_staging.main import app  # pylint: disable=import-error


@pytest.fixture(name="staging_client")
def client_():
    """init fastapi client app."""
    # Test the FastAPI application, opens the database session
    with TestClient(app) as client:
        yield client


@pytest.fixture(name="predefined_config")
def config_():
    """Fixture for pygeoapi yaml config"""
    with open(geoapi_cfg, "r", encoding="utf-8") as yaml_file:
        return yaml.safe_load(yaml_file)


@pytest.fixture(name="mock_jobs")
def dbj_():
    """Fixture used to mock output of tiny db jobs"""
    return [
        {"job_id": "job_1", "status": "started", "progress": 0.0, "detail": TEST_DETAIL},
        {"job_id": "job_2", "status": "in_progress", "progress": 55.0, "detail": TEST_DETAIL},
        {"job_id": "job_3", "status": "paused", "progress": 15.0, "detail": TEST_DETAIL},
        {"job_id": "job_4", "status": "finished", "progress": 100.0, "detail": TEST_DETAIL},
    ]


@pytest.fixture(name="staging_instance")
def staging(mocker):
    """Fixture to mock Staging object"""
    # Mock dependencies for Staging
    mock_credentials = mocker.Mock()
    mock_credentials.headers = {"cookie": "fake-cookie"}
    mock_input_collection = mocker.Mock()
    mock_collection = "test_collection"
    mock_item = "test_item"
    mock_provider = "cadip"
    mock_db = mocker.Mock()  # Mock for tinydb.table.Table
    mock_cluster = mocker.Mock()  # Mock for LocalCluster
    mock_tinydb_lock = mocker.Mock()
    mocker.patch.dict(
        os.environ,
        {
            "RSPY_CATALOG_BUCKET": "fake_bucket",
        },
    )

    # Instantiate the Staging class with the mocked dependencies
    staging_instance = Staging(
        credentials=mock_credentials,
        input_collection=mock_input_collection,
        collection=mock_collection,
        item=mock_item,
        provider=mock_provider,
        db=mock_db,
        cluster=mock_cluster,
        tinydb_lock=mock_tinydb_lock,
    )
    yield staging_instance


@pytest.fixture(name="asyncio_loop", scope="session")
def event_loop():
    """Override the default event loop to ensure proper cleanup."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop

    # Wait for all tasks to complete before closing the loop
    pending = asyncio.all_tasks(loop)  # Get all pending tasks
    if pending:
        loop.run_until_complete(asyncio.gather(*pending))  # Wait for them to finish
    loop.close()
