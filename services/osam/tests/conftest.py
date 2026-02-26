# Copyright 2023-2026 Airbus, CS Group
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

"""Fixtures and tests configuration for OSAM unit tests."""

import os
import os.path as osp
from importlib import reload

from rs_server_common.authentication.keycloak_util import KCUtil

# We are in local mode (no cluster).
# Do this before any other imports.
# flake8: noqa
# pylint: disable=wrong-import-order,wrong-import-position
os.environ["RSPY_LOCAL_MODE"] = "1"
from rs_server_common import settings

reload(settings)


import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import rs_server_osam
from fastapi.testclient import TestClient
from rs_server_osam import main
from rs_server_osam.utils.keycloak_handler import KeycloakHandler
from rs_server_osam.utils.tools import S3StorageConfigurationSingleton

RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / "resources"
CONFIG_CSV = RESOURCES_FOLDER / "expiration_bucket.csv"

os.environ["BUCKET_CONFIG_FILE_PATH"] = str(CONFIG_CSV.absolute())


# Test list for Keycloak users:
#   - one user already linked to an existing obs_user
#   - one user not linked to an obs_user
TEST_KEYCLOAK_USERS_LIST = [
    {"id": "00001", "username": "paul", "enabled": True, "attributes": {"obs-user": "obs1"}},
    {"id": "00002", "username": "emilie", "enabled": True},
]

# Test list for OVH users:
#   - one user linked to an existing Keycloak user
#   - one user linked to an unexisting Keycloak user
#   - one user unrelated to Keycloak users
TEST_OVH_USERS_LIST = [
    {
        "id": "obs1",
        "username": "obs_user_for_existing_keycloak_user",
        "description": "## linked to keycloak user test_user_1",
        "roles": [],
    },
    {
        "id": "obs2",
        "username": "obs_user_for_unexisting_keycloak_user",
        "description": "## linked to keycloak user 99999",
        "roles": [],
    },
    {
        "id": "obs3",
        "username": "unrelated_obs_user",
        "description": "## account linked to an unrelated user",
        "roles": [],
    },
]

# New OVH user to return when asking to create one for Keycloak test user 2
NEW_OVH_USER_WHEN_CREATING = {
    "id": "obs4",
    "username": "newly_created_obs_user_for_test_user_2",
    "description": "## linked to keycloak user 00002",
    "roles": [],
}


@pytest.fixture(scope="function", autouse=True)
def clear_caches():
    """Clear caches at the end of each test"""
    yield
    rs_server_osam.utils.tools.load_configmap_data.cache_clear()


@pytest.fixture(name="mock_keycloak_handler")
def mock_keycloak_handler_():
    """Mock for KeycloakHandler for test_link_rspython_users_and_obs_users"""
    with patch("rs_server_osam.tasks.KeycloakHandler") as mock_keycloak_handler:
        mock_instance = mock_keycloak_handler.return_value
        mock_instance.get_keycloak_users.return_value = TEST_KEYCLOAK_USERS_LIST
        mock_instance.update_keycloak_user.return_value = None
        mock_instance.get_obs_user_from_keycloak_user.side_effect = (
            lambda keycloak_user: KeycloakHandler.get_obs_user_from_keycloak_user(mock_keycloak_handler, keycloak_user)
        )
        mock_instance.set_obs_user_in_keycloak_user.side_effect = (
            lambda keycloak_user, obs_user: KeycloakHandler.set_obs_user_in_keycloak_user(
                mock_keycloak_handler,
                keycloak_user,
                obs_user,
            )
        )
        yield mock_keycloak_handler


@pytest.fixture(name="mock_ovh_handler")
def mock_ovh_handler_():
    """Mock for OVHApiHandler for test_link_rspython_users_and_obs_users"""
    with patch("rs_server_osam.tasks.OVHApiHandler") as mock_ovh_api_handler:
        mock_instance = mock_ovh_api_handler.return_value
        mock_instance.get_all_users.return_value = TEST_OVH_USERS_LIST
        mock_instance.create_user.return_value = NEW_OVH_USER_WHEN_CREATING
        mock_instance.delete_user.return_value = None
        yield mock_ovh_api_handler


@pytest.fixture(name="osam_client", scope="function")
def client_(request, mocker, monkeypatch):
    """init fastapi client app."""

    # Mock cluster/local mode to enable or disable authentication.
    try:
        cluster_mode = not request.param["RSPY_LOCAL_MODE"]

    # By default, force local mode.
    # We use the cluster mode only for the authentication tests.
    except (AttributeError, KeyError):
        cluster_mode = False

    # Patch the env vars and global vars
    monkeypatch.setenv("RSPY_LOCAL_MODE", "0" if cluster_mode else "1")
    mocker.patch("rs_server_common.settings.LOCAL_MODE", new=not cluster_mode, autospec=False)
    mocker.patch("rs_server_common.settings.CLUSTER_MODE", new=cluster_mode, autospec=False)

    # Mock the oauth2 environment variables for the cluster mode
    if cluster_mode:
        monkeypatch.setenv("OIDC_ENDPOINT", "http://OIDC_ENDPOINT")
        monkeypatch.setenv("OIDC_REALM", "OIDC_REALM")
        monkeypatch.setenv("OIDC_CLIENT_ID", "OIDC_CLIENT_ID")
        monkeypatch.setenv("OIDC_CLIENT_SECRET", "OIDC_CLIENT_SECRET")
        monkeypatch.setenv("RSPY_COOKIE_SECRET", "RSPY_COOKIE_SECRET")

    # Patch global vars
    mocker.patch("rs_server_common.authentication.oauth2.KCUTIL", new=KCUtil() if cluster_mode else None)

    # If the main app was previously imported in cluster mode, it has an "authenticate" function dependency.
    # In this case, and if the current unit test is in local mode, then we reload the main app.
    # Same thing if we switch from local mode to cluster mode.
    old_cluster_mode = "authenticate" in [dep.dependency.__name__ for dep in main.dependencies]
    if old_cluster_mode != cluster_mode:
        reload(main)

    # Patch main_osam_task to a no-op so it does NOT start infinite loop thread during tests
    mocker.patch("rs_server_osam.main.main_osam_task", AsyncMock())

    # Test the FastAPI application, opens the database session
    with TestClient(main.app) as client:
        yield client


@pytest.fixture(autouse=True, scope="function")
def reset_s3_singleton():
    """Properly reset singleton state without breaking attribute access."""
    # Only delete the instance — let __new__ recreate everything cleanly
    if hasattr(S3StorageConfigurationSingleton, "instance"):
        del S3StorageConfigurationSingleton.instance

    # Re-initialize class attributes to default (in case they were deleted before)
    for attr, value in [
        ("file_lock", threading.Lock()),
        ("bucket_configuration_csv", []),
        ("config_file_path", ""),
        ("last_config_file_modification_date", 0),
    ]:
        setattr(S3StorageConfigurationSingleton, attr, value)

    yield
