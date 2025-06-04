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
from unittest.mock import MagicMock, patch

import pytest

# pylint: disable = unused-argument
from osam.tasks import (
    DESCRIPTION_TEMPLATE,
    build_s3_rights,
    build_users_data_map,
    delete_obs_user_account_if_not_used_by_keycloak_account,
    get_configmap_user_values,
    link_rspython_users_and_obs_users,
    match_roles,
    parse_role,
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
        description="## linked to keycloak user emilie",
        role="objectstore_operator",
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
        "paul": {"keycloak_attribute": "obs1", "keycloak_roles": []},
        "emilie": {"keycloak_attribute": "obs2", "keycloak_roles": []},
    }

    # Assert initial mapping is correct
    assert build_users_data_map() == expected_user_data_map

    # Update Keycloak attributes
    TEST_KEYCLOAK_USERS_LIST[0].setdefault("attributes", {})["obs-user"] = "updated_obs_value_0"  # type: ignore
    TEST_KEYCLOAK_USERS_LIST[1].setdefault("attributes", {})["obs-user"] = "updated_obs_value_1"  # type: ignore

    # Updated expected mapping
    updated_user_data_map = {
        "paul": {"keycloak_attribute": "updated_obs_value_0", "keycloak_roles": []},
        "emilie": {"keycloak_attribute": "updated_obs_value_1", "keycloak_roles": []},
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
    assert "rspython-ops-catalog-paul" in test_user_1_data[2]
    # Check user_2 allowed buckets.
    test_user_2_data = get_configmap_user_values(TEST_KEYCLOAK_USERS_LIST[1]["username"])
    assert "rspython-ops-catalog" in test_user_2_data[2]
    assert "rspython-ops-catalog-emilie-s1-aux-infinite" in test_user_2_data[2]


@pytest.mark.parametrize(
    "role, expected",
    [
        ("rs_catalog_user1:*_download", ("user1", "*", "download")),
        ("rs_catalog_*:*_read", ("*", "*", "read")),
        ("rs_catalog_DemoUser:*_read", ("DemoUser", "*", "read")),
        ("rs_catalog_*:*_write", ("*", "*", "write")),
        ("invalid_role", None),
    ],
)
def test_parse_role(role, expected):
    """Unittest of parse_role function, should split role into owner, collection, acces_type"""
    assert parse_role(role) == expected


@pytest.mark.parametrize(
    "roles, expected",
    [
        # match_roles([("paul", "s1-l1")]) = {...}
        (
            [("paul", "s1-l1")],
            {
                "rspython-ops-catalog/paul/s1-l1/",
                "rspython-ops-catalog-default-s1-l1/paul/s1-l1/",
                "rspython-ops-catalog-paul/paul/s1-l1/",
            },
        ),
        # match_roles([("copernicus", "s1-l1")])
        (
            [("copernicus", "s1-l1")],
            {
                "rspython-ops-catalog/copernicus/s1-l1/",
                "rspython-ops-catalog-default-s1-l1/copernicus/s1-l1/",
                "rspython-ops-catalog-copernicus-s1-l1/copernicus/s1-l1/",
            },
        ),
        # match_roles([("copernicus", "s1-aux")])
        (
            [("copernicus", "s1-aux")],
            {
                "rspython-ops-catalog/copernicus/s1-aux/",
                "rspython-ops-catalog-copernicus-s1-aux/copernicus/s1-aux/",
                "rspython-ops-catalog-copernicus-s1-aux-infinite/copernicus/s1-aux/",
            },
        ),
        # match_roles([("emilie", "s1-aux")])
        (
            [("emilie", "s1-aux")],
            {
                "rspython-ops-catalog/emilie/s1-aux/",
                "rspython-ops-catalog-emilie-s1-aux-infinite/emilie/s1-aux/",
            },
        ),
        # match_roles([("*", "s1-l1")])
        (
            [("*", "s1-l1")],
            {
                "rspython-ops-catalog/*/s1-l1/",
                "rspython-ops-catalog-default-s1-l1/*/s1-l1/",
                "rspython-ops-catalog-copernicus-s1-l1/*/s1-l1/",
                "rspython-ops-catalog-paul/*/s1-l1/",
            },
        ),
        # match_roles([("emilie", "*")])
        (
            [("emilie", "*")],
            {
                "rspython-ops-catalog/emilie/*/",
                "rspython-ops-catalog-emilie-s1-aux-infinite/emilie/*/",
                "rspython-ops-catalog-default-s1-l1/emilie/*/",
            },
        ),
    ],
)
def test_match_roles(roles, expected):
    """Tests of match_roles, based on input pairs and output roles."""
    assert match_roles(roles) == expected


@pytest.mark.parametrize(
    "user_info, expected",
    [
        (
            {"keycloak_roles": ["rs_catalog_paul:s1-l1_read"]},
            {
                "read": sorted(
                    [
                        "rspython-ops-catalog-paul/paul/s1-l1/",
                        "rspython-ops-catalog-default-s1-l1/paul/s1-l1/",
                        "rspython-ops-catalog/paul/s1-l1/",
                    ],
                ),
                "read_download": [],
                "write_download": [],
            },
        ),
        (
            {"keycloak_roles": ["rs_catalog_copernicus:s1-aux_download"]},
            {
                "read": [],
                "read_download": sorted(
                    [
                        "rspython-ops-catalog/copernicus/s1-aux/",
                        "rspython-ops-catalog-copernicus-s1-aux/copernicus/s1-aux/",
                        "rspython-ops-catalog-copernicus-s1-aux-infinite/copernicus/s1-aux/",
                    ],
                ),
                "write_download": [],
            },
        ),
        (
            {"keycloak_roles": ["rs_catalog_emilie:s1-aux_download"]},
            {
                "read": [],
                "read_download": sorted(
                    [
                        "rspython-ops-catalog/emilie/s1-aux/",
                        "rspython-ops-catalog-emilie-s1-aux-infinite/emilie/s1-aux/",
                    ],
                ),
                "write_download": [],
            },
        ),
        (
            {"keycloak_roles": ["rs_catalog_emilie:*_download"]},
            {
                "read": [],
                "read_download": sorted(
                    [
                        "rspython-ops-catalog/emilie/*/",
                        "rspython-ops-catalog-default-s1-l1/emilie/*/",
                        "rspython-ops-catalog-emilie-s1-aux-infinite/emilie/*/",
                    ],
                ),
                "write_download": [],
            },
        ),
        (
            {"keycloak_roles": ["rs_catalog_copernicus:s1-l1_write"]},
            {
                "read": [],
                "read_download": [],
                "write_download": sorted(
                    [
                        "rspython-ops-catalog/copernicus/s1-l1/",
                        "rspython-ops-catalog-copernicus-s1-l1/copernicus/s1-l1/",
                        "rspython-ops-catalog-default-s1-l1/copernicus/s1-l1/",
                    ],
                ),
            },
        ),
    ],
)
def test_build_s3_rights(user_info, expected):
    """Test build s3 rights"""
    assert build_s3_rights(user_info) == expected


@pytest.mark.usefixtures("mock_ovh_handler", "mock_keycloak_handler")
class TestDeleteObsUser:
    """
    Unit tests for the function `delete_obs_user_account_if_not_used_by_keycloak_account`.

    This test suite verifies that:
    - The function skips deletion if the OBS user description does not contain the expected
      OBS_DESCRIPTION_START marker.
    - No deletion occurs if the OBS user is linked to an existing Keycloak user.
    - The function deletes the OBS user when it is not linked to any Keycloak user and the
      description matches the expected template.
    - No deletion occurs if the OBS user is not linked but the description does not match the template.

    External dependencies like `get_keycloak_user_from_description`, `create_description_from_template`,
    and `get_ovh_handler` are mocked to isolate the function behavior.
    """

    @patch("osam.tasks.get_keycloak_user_from_description")
    @patch("osam.tasks.create_description_from_template")
    @patch("osam.tasks.get_ovh_handler")
    def test_skip_if_not_osam_user(
        self,
        mock_get_ovh_handler,
        mock_create_description,
        mock_get_keycloak_user,
        mock_ovh_handler,
        mock_keycloak_handler,
    ):
        """User description does NOT contain OBS_DESCRIPTION_START → skip deletion"""
        obs_user = {
            "username": "not_osam_user",
            "description": "some unrelated description",
            "id": "obs999",
        }
        with patch("osam.tasks.OBS_DESCRIPTION_START", "## linked to keycloak user"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, [])

        mock_get_keycloak_user.assert_not_called()
        mock_create_description.assert_not_called()
        mock_get_ovh_handler.assert_not_called()

    @patch("osam.tasks.get_keycloak_user_from_description")
    @patch("osam.tasks.create_description_from_template")
    @patch("osam.tasks.get_ovh_handler")
    def test_user_linked_to_keycloak_user_no_deletion(
        self,
        mock_get_ovh_handler,
        mock_create_description,
        mock_get_keycloak_user,
        mock_ovh_handler,
        mock_keycloak_handler,
    ):
        """User is correctly linked to keycloak, skip"""
        obs_user = {
            "username": "obs_user_for_existing_keycloak_user",
            "description": "## linked to keycloak user paul",
            "id": "obs1",
        }
        keycloak_users = [
            {"username": "paul"},
            {"username": "emilie"},
        ]

        mock_get_keycloak_user.return_value = "paul"

        with patch("osam.tasks.OBS_DESCRIPTION_START", "## linked to keycloak user"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)

        mock_get_keycloak_user.assert_called_once_with(obs_user["description"], template=DESCRIPTION_TEMPLATE)
        mock_create_description.assert_not_called()
        mock_get_ovh_handler.assert_not_called()

    @patch("osam.tasks.get_keycloak_user_from_description")
    @patch("osam.tasks.create_description_from_template")
    @patch("osam.tasks.get_ovh_handler")
    def test_user_not_linked_and_description_matches_deletes(
        self,
        mock_get_ovh_handler,
        mock_create_description,
        mock_get_keycloak_user,
        mock_ovh_handler,
        mock_keycloak_handler,
    ):
        """Test user does not exist in keycloak and description match -> delete"""
        obs_user = {
            "username": "obs_user_for_unexisting_keycloak_user",
            "description": "## linked to keycloak user 99999",
            "id": "obs2",
        }
        keycloak_users = [
            {"username": "paul"},
            {"username": "emilie"},
        ]

        mock_get_keycloak_user.return_value = "99999"
        mock_create_description.return_value = obs_user["description"]
        mock_ovh_handler_instance = MagicMock()
        mock_get_ovh_handler.return_value = mock_ovh_handler_instance

        with patch("osam.tasks.OBS_DESCRIPTION_START", "## linked to keycloak user"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)

        mock_get_keycloak_user.assert_called_once_with(obs_user["description"], template=DESCRIPTION_TEMPLATE)
        mock_create_description.assert_called_once_with("99999", template=DESCRIPTION_TEMPLATE)
        mock_ovh_handler_instance.delete_user.assert_called_once_with(obs_user["id"])

    @patch("osam.tasks.get_keycloak_user_from_description")
    @patch("osam.tasks.create_description_from_template")
    @patch("osam.tasks.get_ovh_handler")
    def test_user_not_linked_but_description_differs_no_deletion(
        self,
        mock_get_ovh_handler,
        mock_create_description,
        mock_get_keycloak_user,
        mock_ovh_handler,
        mock_keycloak_handler,
    ):
        """Test user doesn't exist in keycloak but description doesnt match -> skip"""
        obs_user = {
            "username": "obs_user_for_unexisting_keycloak_user",
            "description": "## linked to keycloak user 99999",
            "id": "obs2",
        }
        keycloak_users = [
            {"username": "paul"},
            {"username": "emilie"},
        ]

        mock_get_keycloak_user.return_value = "99999"
        mock_create_description.return_value = "different description"
        mock_ovh_handler_instance = MagicMock()
        mock_get_ovh_handler.return_value = mock_ovh_handler_instance

        with patch("osam.tasks.OBS_DESCRIPTION_START", "## linked to keycloak user"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)

        mock_get_keycloak_user.assert_called_once_with(obs_user["description"], template=DESCRIPTION_TEMPLATE)
        mock_create_description.assert_called_once_with("99999", template=DESCRIPTION_TEMPLATE)
        mock_ovh_handler_instance.delete_user.assert_not_called()
