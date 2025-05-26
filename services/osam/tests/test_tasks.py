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

from osam.tasks import link_rspython_users_and_obs_users

from .conftest import TEST_KEYCLOAK_USERS_LIST


def test_link_rspython_users_and_obs_users(mock_keycloak_handler, mock_ovh_handler):
    """Main unit test for link_rspython_users_and_obs_users"""

    # Run function with test data and mocks and fixtures from conftest
    link_rspython_users_and_obs_users()

    # Creation of new OVH users: assert that create_user is called ONCE
    # (there is only one Keycloak user in the test data without an OVH user linked)
    updated_keycloak_user = TEST_KEYCLOAK_USERS_LIST[1]
    updated_keycloak_user["attributes"]["obs-user"] = "obs4"
    mock_ovh_handler.return_value.create_user.assert_called_once_with(description="## linked to keycloak user 00002")
    mock_keycloak_handler.return_value.update_keycloak_user.assert_called_once_with(
        updated_keycloak_user["id"],
        updated_keycloak_user,
    )

    # Deletion of OVH users not linked to Keycloak users: assert that delete_user is called ONCE
    # (there are two users that are not linked to Keycloak users but only one has a fitting description)
    mock_ovh_handler.return_value.delete_user.assert_called_once_with("obs2")

    assert True
