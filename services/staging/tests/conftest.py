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

# pylint: disable=C0413, ungrouped-imports
# flake8: noqa: F402

import asyncio
import os
import os.path as osp
import threading
from datetime import datetime
from importlib import reload
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.utils.pytest.pytest_authentication_utils import (
    init_app_cluster_mode,
)

# Init the FastAPI application with all the cluster mode features (local mode=0)
# Do this before any other imports.
# We'll restore the local mode by default a few lines below.
# pylint: disable=wrong-import-position
init_app_cluster_mode()


# These env vars are mandatory before importing the staging main module
for envvar in "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB":
    os.environ[envvar] = ""
from rs_server_common import settings as common_settings
from rs_server_staging.main import app  # pylint: disable=import-error

# Restore the local mode by default
os.environ["RSPY_LOCAL_MODE"] = "1"
reload(common_settings)

from rs_server_common.authentication.authentication_to_external import (  # pylint: disable=import-error
    ExternalAuthenticationConfig,
)
from rs_server_staging.processors import (  # pylint: disable=import-error
    RefreshTokenData,
    Staging,
)

TEST_DETAIL = "Test detail"


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


@pytest.fixture(name="staging_client")
def client_(mocker):
    """init fastapi client app."""
    # Test the FastAPI application, opens the database session
    mocker.patch("rs_server_staging.main.init_db", return_value=None)
    mocker.patch("rs_server_staging.main.PostgreSQLManager", return_value=mocker.Mock())
    with TestClient(app) as client:

        yield client

        os.environ["RSPY_LOCAL_MODE"] = "1"
        reload(common_settings)


@pytest.fixture(name="geoapi_cfg")
def geoapi_cfg_() -> Path:
    """Return pygeoapi config file path"""
    return Path(osp.realpath(osp.dirname(__file__))) / "resources" / "test_config.yml"


@pytest.fixture(name="predefined_config")
def config_(geoapi_cfg):
    """Fixture for pygeoapi yaml config"""
    with open(geoapi_cfg, encoding="utf-8") as yaml_file:
        return yaml.safe_load(yaml_file)


@pytest.fixture(name="mock_jobs")
def dbj_():
    """Fixture used to mock output of tiny db jobs"""
    return [
        {
            "identifier": "job_1",
            "status": "running",
            "type": "process",
            "progress": 0.0,
            "message": TEST_DETAIL,
            "created": datetime(2024, 1, 1, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated": datetime(2024, 1, 1, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "processID": "staging",
        },
        {
            "identifier": "job_2",
            "status": "running",
            "type": "process",
            "progress": 55.0,
            "message": TEST_DETAIL,
            "created": datetime(2024, 1, 2, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated": datetime(2024, 1, 2, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "processID": "staging",
        },
        {
            "identifier": "job_3",
            "status": "running",
            "type": "process",
            "progress": 15.0,
            "message": TEST_DETAIL,
            "created": datetime(2024, 1, 3, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated": datetime(2024, 1, 3, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "processID": "staging",
        },
        {
            "identifier": "job_4",
            "status": "successful",
            "type": "process",
            "progress": 100.0,
            "message": TEST_DETAIL,
            "created": datetime(2024, 1, 4, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated": datetime(2024, 1, 4, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "processID": "staging",
        },
    ]


def feature(f_id: str) -> dict:
    """Create a new empty Feature"""
    return {
        "type": "Feature",
        "properties": {},
        "id": f_id,
        "stac_version": "1.0.0",
        "assets": {"asset1": {"href": "https://fake-data"}},
        "stac_extensions": [],
    }


@pytest.fixture(name="staging_inputs")
def staging_inputs():
    """Fixture to mock the staging execution inputs"""
    return {
        "collection": "test_collection",
        "items": {"value": {"type": "FeatureCollection", "features": [feature("1"), feature("2")]}},
    }


@pytest.fixture(name="staging_instance")
def staging(mocker, config):
    """Fixture to mock the Staging object"""
    # Mock dependencies for Staging
    mock_request = mocker.Mock()
    mock_request.headers = {"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"}
    mock_db = mocker.Mock()  # Mock for PostgreSQL Manager
    mock_cluster = mocker.Mock()  # Mock for LocalCluster
    # Mock station_token_list as an iterable

    # Mock RefreshTokenData objects
    mock_refresh_token1 = mocker.MagicMock(spec=RefreshTokenData)
    mock_refresh_token1.config = config
    mock_refresh_token1.token_dict = {
        "access_token": "P4JSuo3gfQxKo0gfbQTb7nDn5OkzWP3umdGvy7G3CcI",
        "expires_in": 3600,
        "access_token_creation_date": datetime.now(),
        "refresh_token": "fakeRefreshToken",
        "refresh_expires_in": 7200,
        "refresh_token_creation_date": datetime.now(),
        "token_type": "Bearer",
    }

    mock_refresh_token1.subscribers = 1
    mock_refresh_token1.station_id = mocker.Mock(return_value=config.station_id)

    # Mock station_token_list as a list of RefreshTokenData instances
    mock_station_token_list = [mock_refresh_token1]

    # Fix: Explicitly define __enter__ and __exit__ on mocker.Mock()
    mock_station_token_list_lock = mocker.Mock()
    mock_station_token_list_lock.__enter__ = mocker.Mock(return_value=mock_station_token_list_lock)
    mock_station_token_list_lock.__exit__ = mocker.Mock(return_value=None)

    mocker.patch.dict(
        os.environ,
        {
            "RSPY_CATALOG_BUCKET": "fake_bucket",
        },
    )

    # Instantiate the Staging class with the mocked dependencies
    staging_instance = Staging(
        request=mock_request,
        db_process_manager=mock_db,
        cluster=mock_cluster,
        station_token_list=mock_station_token_list,
        station_token_list_lock=mock_station_token_list_lock,
    )
    # mock streaming list
    staging_instance.stream_list = [mocker.Mock(id=1), mocker.Mock(id=2)]
    # mock assets_info
    staging_instance.assets_info = [
        ("https://cadip/some_asset_1", "some_asset_1"),
        ("https://cadip/some_asset_2", "some_asset_2"),
    ]
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


@pytest.fixture(name="config")
def authentication_config():
    """Return an example of external authentication configuration"""
    return ExternalAuthenticationConfig(
        station_id="cadip",
        domain="https://127.0.0.1:5000",
        service_name="cadip",
        service_url="https://127.0.0.1:5000/oauth2/token",
        auth_type="oauth2",
        token_url="https://127.0.0.1:5000/oauth2/token",
        grant_type="password",
        username="test",
        # nosec B106
        password="DUMMY_PASSWORD",
        client_id="client_id",
        client_secret="client_secret",  # nosec B106
    )


@pytest.fixture(name="mock_app")
def get_mock_app(mocker, staging_client):
    """
    Mock the FastAPI application variable
    """
    mock_app = mocker.patch.object(
        staging_client.app,
        "extra",
        {
            "station_token_list": mocker.MagicMock(),  # Mock auth list to prevent KeyError
            "station_token_list_lock": mocker.Mock(spec=threading.Lock),
        },
    )
    return mock_app


@pytest.fixture(name="mock_db_table")
def get_mock_db_table(mocker):
    """
    Mock the database manager
    """
    mock_db_table = mocker.MagicMock()
    mock_db_table.get_jobs.return_value = {
        "jobs": [
            {
                "identifier": "job_1",
                "status": "successful",
                "type": "process",
                "progress": 100.0,
                "message": TEST_DETAIL,
                "created": datetime(2024, 1, 1, 12, 0, 0),
                "updated": datetime(2024, 1, 1, 13, 0, 0),
                "processID": "staging",
            },
            {
                "identifier": "job_2",
                "status": "running",
                "type": "process",
                "progress": 90.25,
                "message": TEST_DETAIL,
                "created": datetime(2024, 1, 2, 12, 0, 0),
                "updated": datetime(2024, 1, 2, 13, 0, 0),
                "processID": "staging",
            },
        ],
        "numberMatched": 2,
    }
    return mock_db_table


@pytest.fixture(name="cluster")
def cluster_with_options(mocker):
    """Fixture to get a cluster with options"""
    cluster_options = {
        "cluster_max_cores": 4,
        "cluster_max_memory": 17179869184,
        "cluster_max_workers": 5,
        "cluster_name": "dask-tests",
        "environment": {
            "S3_ENDPOINT": "https://fake-s3-endpoint",
            "S3_REGION": "fake-region",
            "TEMPO_ENDPOINT": "fake-tempo",
        },
        "image": "fake-image",
        "namespace": "dask-gateway",
        "scheduler_extra_container_config": {"imagePullPolicy": "Always"},
        "scheduler_extra_pod_annotations": {"access": "internal", "usage": "unknown"},
        "scheduler_extra_pod_labels": {"cluster_name": "dask-tests"},
        "worker_cores": 1,
        "worker_extra_container_config": {"envFrom": [{"secretRef": {"name": "obs"}}]},
        "worker_extra_pod_config": {
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {"key": "fake-node-role.kubernetes.io/fake-infra", "operator": "Exists"},
                                ],
                            },
                        ],
                    },
                },
            },
        },
        "worker_memory": 2,
    }
    # Mock the Security object
    mock_security = mocker.patch("dask.distributed.Security")
    # Mock the cluster with the required attributes for Client
    mock_cluster = mocker.Mock()
    mock_cluster.name = "dask-gateway-id"
    mock_cluster.options = cluster_options
    mock_cluster.dashboard_link = "https://mock-dashboard"
    mock_cluster.scheduler_address = "tcp://mock-scheduler-address"  # Set a valid scheduler address
    mock_cluster.security = mock_security  # Add mocked security attribute
    return mock_cluster


@pytest.fixture(name="client")
def dask_client(mocker, cluster):
    """
    Mock the dask client
    """
    client = mocker.Mock(return_value=True)
    client.cluster = cluster
    client.nthreads = mocker.Mock(return_value={0: 1, 1: 1})  # Simulate 2 threads
    client.submit = mocker.Mock(return_value=mocker.Mock())  # Simulating a Dask future
    return client
