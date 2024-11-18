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
from datetime import datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

os.environ["RSPY_LOCAL_MODE"] = "1"
from rs_server_staging.processors import Staging  # pylint: disable=import-error

# set pygeoapi env variables
geoapi_cfg = Path(osp.realpath(osp.dirname(__file__))) / "resources" / "test_config.yml"
os.environ["PYGEOAPI_CONFIG"] = str(geoapi_cfg)
os.environ["PYGEOAPI_OPENAPI"] = ""

TEST_DETAIL = "Test detail"

from rs_server_staging.main import app  # pylint: disable=import-error


@pytest.fixture(name="staging_client")
def client_(mocker):
    """init fastapi client app."""
    # Test the FastAPI application, opens the database session
    mocker.patch("rs_server_staging.main.init_db", return_value=None)
    mocker.patch(
        "rs_server_staging.main.get_manager_def",
        return_value={
            "name": "test_pgmanager",
            "connection": {
                "host": os.environ["POSTGRES_HOST"],
                "port": os.environ["POSTGRES_PORT"],
                "database": os.environ["POSTGRES_DB"],
                "user": os.environ["POSTGRES_USER"],
                "password": os.environ["POSTGRES_PASSWORD"],
            },
        },
    )
    mocker.patch("rs_server_staging.main.PostgreSQLManager", return_value=mocker.Mock())
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
        {
            "identifier": "job_1",
            "status": "started",
            "progress": 0.0,
            "detail": TEST_DETAIL,
            "created_at": str(datetime(2024, 1, 1, 12, 0, 0)),
            "updated_at": str(datetime(2024, 1, 1, 13, 0, 0)),
        },
        {
            "identifier": "job_2",
            "status": "in_progress",
            "progress": 55.0,
            "detail": TEST_DETAIL,
            "created_at": str(datetime(2024, 1, 2, 12, 0, 0)),
            "updated_at": str(datetime(2024, 1, 2, 13, 0, 0)),
        },
        {
            "identifier": "job_3",
            "status": "paused",
            "progress": 15.0,
            "detail": TEST_DETAIL,
            "created_at": str(datetime(2024, 1, 3, 12, 0, 0)),
            "updated_at": str(datetime(2024, 1, 3, 13, 0, 0)),
        },
        {
            "identifier": "job_4",
            "status": "finished",
            "progress": 100.0,
            "detail": TEST_DETAIL,
            "created_at": str(datetime(2024, 1, 4, 12, 0, 0)),
            "updated_at": str(datetime(2024, 1, 4, 13, 0, 0)),
        },
    ]


@pytest.fixture(name="set_db_env_var")
def set_db_env_var_fixture(monkeypatch):
    """Fixture to set environment variables for simulating the mounting of
    the external station token secrets in kubernetes.

    This fixture sets a variety of environment variables related to token-based
    authentication for different services, allowing tests to be executed with
    the correct configurations in place.
    The enviornment variables set are managing 3 stations:
    - adgs (service auxip)
    - ins (service cadip)
    - mps (service cadip)

    Args:
        monkeypatch: Pytest utility for temporarily modifying environment variables.
    """
    envvars = {
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "password",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5500",
        "POSTGRES_DB": "rspy_pytest",
    }
    for key, val in envvars.items():
        monkeypatch.setenv(key, val)
    yield  # restore the environment


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
    mock_db = mocker.Mock()  # Mock for PostgreSQL Manager
    mock_cluster = mocker.Mock()  # Mock for LocalCluster

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
        db_process_manager=mock_db,
        cluster=mock_cluster,
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
