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

"""Unit tests for keycloak_handler"""

import os

import pytest
from keycloak.exceptions import KeycloakConnectionError, KeycloakPutError
from osam.utils.keycloak_handler import KeycloakHandler


@pytest.fixture(name="handler")
def handler_fixture(mocker):
    """
    Fixture to initialize KeycloakHandler with patched KeycloakAdmin and KeycloakOpenIDConnection.
    """
    # Patch environment variables
    mocker.patch.dict(
        os.environ,
        {
            "OIDC_ENDPOINT": "http://fake-keycloak",
            "OIDC_REALM": "fake-realm",
            "OIDC_CLIENT_ID": "fake-client",
            "OIDC_CLIENT_SECRET": "secret",
        },
    )

    # Patch KeycloakAdmin and KeycloakOpenIDConnection
    mock_admin_instance = mocker.MagicMock()
    mocker.patch("osam.utils.keycloak_handler.KeycloakOpenIDConnection")
    mocker.patch("osam.utils.keycloak_handler.KeycloakAdmin", return_value=mock_admin_instance)

    return KeycloakHandler()


def test_get_keycloak_users(handler):
    """
    Test that get_keycloak_users returns the list of users.
    """

    handler.keycloak_admin.get_users.return_value = [{"id": "123"}]

    result = handler.get_keycloak_users()
    assert result == [{"id": "123"}]
    handler.keycloak_admin.get_users.assert_called_once_with({})


def test_get_keycloak_user_roles(handler):
    """
    Test retrieval of user roles combining group and realm roles.
    """

    handler.keycloak_admin.get_user_groups.return_value = [{"id": "group1"}]
    handler.keycloak_admin.get_group_realm_roles.return_value = [{"name": "role1"}]
    handler.keycloak_admin.get_realm_roles_of_user.return_value = [{"name": "role2"}]

    result = handler.get_keycloak_user_roles("user123")
    assert {r["name"] for r in result} == {"role1", "role2"}


def test_get_obs_user_from_keycloak_user_existing(handler):
    """
    Test extracting 'obs-user' when present.
    """

    user = {"attributes": {"obs-user": "obs123"}}
    assert handler.get_obs_user_from_keycloak_user(user) == "obs123"


def test_get_obs_user_from_keycloak_user_missing(handler):
    """
    Test extracting 'obs-user' when attribute is missing.
    """

    user = {"attributes": {}}  # type: ignore
    assert handler.get_obs_user_from_keycloak_user(user) is None


def test_get_obs_user_from_keycloak_username_with_list(handler):
    """
    Test get_obs_user_from_keycloak_username when 'obs-user' is a list.
    """

    handler.keycloak_admin.get_user_id.return_value = "user123"
    handler.keycloak_admin.get_user.return_value = {"attributes": {"obs-user": ["obs123"]}}

    result = handler.get_obs_user_from_keycloak_username("testuser")
    assert result == "obs123"


def test_get_obs_user_from_keycloak_username_with_str(handler):
    """
    Test get_obs_user_from_keycloak_username when 'obs-user' is a string.
    """

    handler.keycloak_admin.get_user_id.return_value = "user123"
    handler.keycloak_admin.get_user.return_value = {"attributes": {"obs-user": "obs123"}}

    result = handler.get_obs_user_from_keycloak_username("testuser")
    assert result == "obs123"


def test_get_obs_user_from_keycloak_username_missing(handler):
    """
    Test get_obs_user_from_keycloak_username when 'obs-user' is missing.
    """

    handler.keycloak_admin.get_user_id.return_value = "user123"
    handler.keycloak_admin.get_user.return_value = {}

    result = handler.get_obs_user_from_keycloak_username("testuser")
    assert result is None


def test_get_obs_user_from_keycloak_username_keycloak_error(handler):
    """
    Test get_obs_user_from_keycloak_username raising KeycloakConnectionError.
    """
    handler.keycloak_admin.get_user_id.side_effect = KeycloakConnectionError("connection error")

    with pytest.raises(KeycloakConnectionError):
        handler.get_obs_user_from_keycloak_username("testuser")


def test_set_obs_user_in_keycloak_user(handler):
    """
    Test setting 'obs-user' attribute in a Keycloak user.
    """
    keycloak_user = {"id": "user123", "attributes": {}}
    handler.set_obs_user_in_keycloak_user(keycloak_user, "obs123")
    handler.keycloak_admin.update_user.assert_called_once_with(
        user_id="user123",
        payload={"attributes": {"obs-user": ["obs123"]}},
    )


def test_update_keycloak_user_success(handler):
    """
    Test successful update of Keycloak user.
    """

    handler.update_keycloak_user("user123", {"firstName": "NewName"})
    handler.keycloak_admin.update_user.assert_called_once_with(
        user_id="user123",
        payload={"firstName": "NewName"},
    )


def test_update_keycloak_user_failure(handler):
    """
    Test update_keycloak_user raising RuntimeError on KeycloakPutError.
    """

    handler.keycloak_admin.update_user.side_effect = KeycloakPutError("error", response_code=400)
    with pytest.raises(RuntimeError) as exc_info:
        handler.update_keycloak_user("user123", {})

    assert "Could not update client" in str(exc_info.value)
