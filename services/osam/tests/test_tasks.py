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

"""Unit tests for tasks"""
# pylint: disable = unused-argument
from osam.tasks import (
    build_users_data_map,
    get_configmap_user_values,
    link_rspython_users_and_obs_users,
)

from .conftest import TEST_KEYCLOAK_USERS_LIST


def test_link_rspython_users_and_obs_users(mock_keycloak_handler, mock_ovh_handler):
    """Main unit test for link_rspython_users_and_obs_users"""

    # Run function with test data and mocks and fixtures from conftest
    link_rspython_users_and_obs_users()

    # Creation of new OVH users: assert that create_user is called ONCE
    # (there is only one Keycloak user in the test data without an OVH user linked)
    updated_keycloak_user = TEST_KEYCLOAK_USERS_LIST[1]
    updated_keycloak_user.setdefault("attributes", {})["obs-user"] = "obs2"  # type: ignore
    mock_ovh_handler.return_value.create_user.assert_called_once_with(
        description="## linked to keycloak user test_user_2",
    )
    mock_keycloak_handler.return_value.set_obs_user_in_keycloak_user.assert_called_once_with(
        updated_keycloak_user,
        "obs4",
    )

    # Deletion of OVH users not linked to Keycloak users: assert that delete_user is called ONCE
    # (there are two users that are not linked to Keycloak users but only one has a fitting description)
    mock_ovh_handler.return_value.delete_user.assert_called_with("obs2")

    assert True


def test_build_users_data_map(mock_keycloak_handler):
    """Test that values received from Keycloak are correctly mapped to user data"""

    # Initial expected mapping
    expected_user_data_map = {
        "test_user_1": {"keycloak_attribute": "obs1", "keycloak_roles": []},
        "test_user_2": {"keycloak_attribute": "obs2", "keycloak_roles": []},
    }

    # Assert initial mapping is correct
    assert build_users_data_map() == expected_user_data_map

    # Update Keycloak attributes
    TEST_KEYCLOAK_USERS_LIST[0].setdefault("attributes", {})["obs-user"] = "updated_obs_value_0"  # type: ignore
    TEST_KEYCLOAK_USERS_LIST[1].setdefault("attributes", {})["obs-user"] = "updated_obs_value_1"  # type: ignore

    # Updated expected mapping
    updated_user_data_map = {
        "test_user_1": {"keycloak_attribute": "updated_obs_value_0", "keycloak_roles": []},
        "test_user_2": {"keycloak_attribute": "updated_obs_value_1", "keycloak_roles": []},
    }

    # Assert updated mapping is correct
    assert build_users_data_map() == updated_user_data_map
    # Replace to initial state
    TEST_KEYCLOAK_USERS_LIST[0].setdefault("attributes", {})["obs-user"] = "obs1"  # type: ignore
    TEST_KEYCLOAK_USERS_LIST[1].setdefault("attributes", {})["obs-user"] = "obs2"  # type: ignore


def test_get_configmap_user_values():
    """Test values received from configmap based on user."""
    # Check user_1 allowed buckets.
    test_user_1_data = get_configmap_user_values(TEST_KEYCLOAK_USERS_LIST[0]["username"])
    assert [
        "rs-dev-cluster-catalog",
        "rs-dev-cluster-catalog-aux-orbsct",
        "rs-dev-cluster-catalog-test_user_1-bucket",
    ] in test_user_1_data
    # Check user_2 allowed buckets.
    test_user_2_data = get_configmap_user_values(TEST_KEYCLOAK_USERS_LIST[1]["username"])
    assert ["rs-dev-cluster-catalog", "rs-dev-cluster-catalog-aux-orbsct"] in test_user_2_data


def test_parse_role():
    """."""
    assert True


def test_match_roles():
    """."""
    assert True


def test_build_s3_rights():
    """."""
    assert True
