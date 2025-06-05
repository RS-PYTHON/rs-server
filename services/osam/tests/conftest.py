# Copyright 2025 CS Group
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
from pathlib import Path
from unittest.mock import patch

import pytest
from osam.utils.keycloak_handler import KeycloakHandler

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


@pytest.fixture(name="mock_keycloak_handler")
def mock_keycloak_handler_():
    """Mock for KeycloakHandler for test_link_rspython_users_and_obs_users"""
    with patch("osam.tasks.KeycloakHandler") as mock_keycloak_handler:
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
    with patch("osam.tasks.OVHApiHandler") as mock_ovh_api_handler:
        mock_instance = mock_ovh_api_handler.return_value
        mock_instance.get_all_users.return_value = TEST_OVH_USERS_LIST
        mock_instance.create_user.return_value = NEW_OVH_USER_WHEN_CREATING
        mock_instance.delete_user.return_value = None
        yield mock_ovh_api_handler
