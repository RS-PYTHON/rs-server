# Copyright 2023-2025 Airbus, CS Group
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

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from ovh.exceptions import BadParametersError

# pylint: disable = unused-argument,no-name-in-module
from rs_server_osam.tasks import (
    apply_user_access_policy,
    build_s3_rights,
    build_users_data_map,
    delete_obs_user_account_if_not_used_by_keycloak_account,
    get_user_s3_credentials,
    link_rspython_users_and_obs_users,
    update_s3_rights_lists,
)
from rs_server_osam.utils.tools import DESCRIPTION_TEMPLATE


class TestLinkRspythonUsersAndObsUsers:
    """
    Unit tests for the function `link_rspython_users_and_obs_users`.

    This test suite validates the synchronization logic between Keycloak users
    and OBS (OVH Object Storage) users, focusing on creation, linking, and cleanup
    behavior.

    Specifically, it verifies that:
    - A new OBS user account is created when a Keycloak user has no `obs-user`
      attribute.
    - A new OBS user account is created when a Keycloak user has an `obs-user`
      attribute, but the referenced OBS user ID does not exist in OVH.
    - No OBS user account is created when a Keycloak user is already correctly
      linked to an existing OBS user in OVH.
    - OBS user accounts linked to existing Keycloak users are never deleted.
    - OBS user accounts that are not linked to any Keycloak user are deleted
      only if their description matches the expected description template
      (as defined by `LIST_CHECK_OVH_DESCRIPTION`).
    - OBS user accounts that are not linked to any Keycloak user but whose
      description does not match the expected template are preserved.

    External dependencies such as Keycloak and OVH handlers are mocked to ensure
    the tests focus exclusively on the internal decision logic of the function.
    """

    def test_no_creation_when_all_keycloak_users_are_linked(self, mock_keycloak_handler, mock_ovh_handler):
        """All Keycloak users already linked to existing OBS users"""
        # Create keycloak user alice with a obs-user attribute linked to obs1
        mock_keycloak_handler.return_value.get_keycloak_users.return_value = [
            {
                "username": "alice",
                "attributes": {"obs-user": ["obs1"]},
            },
        ]

        # Create OVH user obs1 linked to alice with a descripton containing the expected template
        mock_ovh_handler.return_value.get_all_users.return_value = [
            {"id": "obs1", "username": "alice-obs", "description": "## linked to keycloak user alice from platform X"},
        ]

        link_rspython_users_and_obs_users()

        # Test that no new OBS user is created and no existing OBS user is deleted
        mock_ovh_handler.return_value.create_user.assert_not_called()
        mock_ovh_handler.return_value.delete_user.assert_not_called()

    def test_creation_when_obs_attribute_missing(self, mock_keycloak_handler, mock_ovh_handler):
        """Keycloak user without obs-user attribute → create new OBS user and link it in Keycloak"""
        # Create keycloak user bob without obs-user attribute
        mock_keycloak_handler.return_value.get_keycloak_users.return_value = [
            {"username": "bob", "id": "00002", "enabled": True},
        ]
        # No OVH users
        mock_ovh_handler.return_value.get_all_users.return_value = []

        link_rspython_users_and_obs_users()

        # Check that a new OBS user is created and linked to the Keycloak user bopb
        mock_ovh_handler.return_value.create_user.assert_called_once_with(
            description="## linked to keycloak user bob",
            role="objectstore_operator",
        )
        mock_keycloak_handler.return_value.set_obs_user_in_keycloak_user.assert_called_once()

    def test_creation_when_obs_id_not_found_in_ovh(self, mock_keycloak_handler, mock_ovh_handler):
        """Keycloak user with obs-user attribute but the associated OBS user ID is not found in OVH
        → create new OBS user and link it in Keycloak"""
        mock_keycloak_handler.return_value.get_keycloak_users.return_value = [
            {
                "username": "toto",
                "id": "00003",
                "enabled": True,
                "attributes": {"obs-user": ["obs-missing"]},
            },
        ]
        # OVH contains a user that is not related to Toto
        mock_ovh_handler.return_value.get_all_users.return_value = [
            {
                "id": "obs-existing",
                "username": "NOT_TOTO",
                "description": "## linked to keycloak user NOT_TOTO from platform Y",
            },
        ]

        link_rspython_users_and_obs_users()
        # Check that new OBS is created with correct description
        mock_ovh_handler.return_value.create_user.assert_called_once_with(
            description="## linked to keycloak user toto",
            role="objectstore_operator",
        )

    def test_no_deletion_when_obs_user_is_linked(self, mock_keycloak_handler, mock_ovh_handler):
        """OBS user linked to an existing Keycloak user → no deletion"""
        mock_keycloak_handler.return_value.get_keycloak_users.return_value = [
            {
                "username": "toto",
                "id": "00001",
                "attributes": {"obs-user": ["obs1"]},
            },
        ]
        # OVH contains a user obs1 linked to toto with a description containing the expected template
        mock_ovh_handler.return_value.get_all_users.return_value = [
            {"id": "obs1", "username": "toto-obs", "description": "## linked to keycloak user toto from platform X"},
        ]

        link_rspython_users_and_obs_users()
        # Check that no OBS user is deleted
        mock_ovh_handler.return_value.delete_user.assert_not_called()

    def test_deletion_when_obs_user_not_linked_anymore(self, mock_keycloak_handler, mock_ovh_handler, monkeypatch):
        """OBS user not linked to any Keycloak user and description contains the expected template → deletion"""
        monkeypatch.setattr(
            "rs_server_osam.tasks.LIST_CHECK_OVH_DESCRIPTION",
            ["## linked to keycloak user ", ""],
        )
        # No Keycloak users
        mock_keycloak_handler.return_value.get_keycloak_users.return_value = []
        # OVH contains a user with a description containing the expected template
        mock_ovh_handler.return_value.get_all_users.return_value = [
            {"id": "00002", "username": "obs-toto", "description": "## linked to keycloak user toto"},
        ]

        link_rspython_users_and_obs_users()
        # Check that the OBS user is deleted
        mock_ovh_handler.return_value.delete_user.assert_called_once_with("00002")

    def test_link_rspython_users_and_obs_users_raises_on_exception(
        self,
        mock_keycloak_handler,
        mock_ovh_handler,
        caplog,
    ):
        """Test that link_rspython_users_and_obs_users raises RuntimeError if an exception occurs."""
        mock_keycloak_handler.return_value.get_keycloak_users.return_value = [
            {"username": "alice", "id": "00001", "attributes": {"obs-user": ["obs1"]}},
        ]

        with patch("rs_server_osam.tasks.get_ovh_handler") as mock_ovh:
            mock_ovh.return_value.get_all_users.side_effect = Exception("OVH API failure")
            with pytest.raises(Exception) as excinfo:
                link_rspython_users_and_obs_users()

            assert "OVH API failure" in str(excinfo.value)


def test_build_users_data_map(mocker):
    """
    Test that build_users_data_map correctly maps Keycloak users to their attributes
    and roles, including updates.
    """

    # --- Setup mock handler ---
    mock_handler = mocker.Mock()

    # Mock users returned from Keycloak
    mock_handler.get_keycloak_users.return_value = [
        {"id": "1", "username": "paul"},
        {"id": "2", "username": "emilie"},
    ]

    # Mock obs attribute for each user
    def mock_get_obs_user(user):
        mapping = {"paul": "obs1", "emilie": "obs2"}
        return mapping[user["username"]]

    mock_handler.get_obs_user_from_keycloak_user.side_effect = mock_get_obs_user

    # Mock roles (empty lists for simplicity)
    def mock_get_roles(user_id):
        return []

    mock_handler.get_keycloak_user_roles.side_effect = mock_get_roles

    # Patch get_keycloak_handler to return our mock
    mocker.patch("rs_server_osam.tasks.get_keycloak_handler", return_value=mock_handler)

    # --- Test initial mapping ---
    expected_initial_map = {
        "paul": {"keycloak_attribute": "obs1", "keycloak_roles": []},
        "emilie": {"keycloak_attribute": "obs2", "keycloak_roles": []},
    }

    assert build_users_data_map() == expected_initial_map

    # --- Test updated values ---
    def mock_get_obs_user_updated(user):
        mapping = {"paul": "updated_obs_value_0", "emilie": "updated_obs_value_1"}
        return mapping[user["username"]]

    mock_handler.get_obs_user_from_keycloak_user.side_effect = mock_get_obs_user_updated

    expected_updated_map = {
        "paul": {"keycloak_attribute": "updated_obs_value_0", "keycloak_roles": []},
        "emilie": {"keycloak_attribute": "updated_obs_value_1", "keycloak_roles": []},
    }

    assert build_users_data_map() == expected_updated_map


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
        # Testcase compliant with rspy604 example, note that duplicates are not showed.
        # Also, as per priority list, if a user have permission to write_download in rspython-ops-catalog/paul/s1-l1/
        # it also have read, read_download permission, even if not mentioned in that list.
        (
            {"keycloak_roles": ["rs_catalog_paul:s1-l1_write"]},
            {
                "read": [],
                "read_download": [],
                "write_download": sorted(
                    [
                        "rspython-ops-catalog-default-s1-l1/paul/s1-l1/",
                        "rspython-ops-catalog-paul/paul/s1-l1/",
                        "rspython-ops-catalog/paul/s1-l1/",
                    ],
                ),
            },
        ),
        # Testcase when the roles from the keycloak are not compliant
        (
            {"keycloak_roles": ["rsnotcompliant"]},
            {
                "read": [],
                "read_download": [],
                "write_download": [],
            },
        ),
    ],
)
def test_build_s3_rights(user_info, expected):
    """Test build s3 rights"""
    assert build_s3_rights(user_info) == expected


@pytest.mark.parametrize(
    "s3_rights, expected",
    [
        (
            {
                "read": [
                    "rspython-ops-catalog-paul/paul/s1-l1/",
                    "rspython-ops-catalog-default-s1-l1/paul/s1-l1/",
                    "rspython-ops-catalog/paul/s1-l1/",
                ],
                "read_download": [],
                "write_download": [],
            },
            {
                "Version": "2025-01-01",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-paul",
                        "Condition": {"StringLike": {"s3:prefix": ["paul/s1-l1/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-default-s1-l1",
                        "Condition": {"StringLike": {"s3:prefix": ["paul/s1-l1/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog",
                        "Condition": {"StringLike": {"s3:prefix": ["paul/s1-l1/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetBucketLocation"],
                        "Resource": [
                            "arn:aws:s3:::rspython-ops-catalog-paul/paul/s1-l1/*",
                            "arn:aws:s3:::rspython-ops-catalog-default-s1-l1/paul/s1-l1/*",
                            "arn:aws:s3:::rspython-ops-catalog/paul/s1-l1/*",
                        ],
                    },
                ],
            },
        ),
        (
            {
                "read": [],
                "read_download": [
                    "rspython-ops-catalog/copernicus/s1-aux/",
                    "rspython-ops-catalog-copernicus-s1-aux/copernicus/s1-aux/",
                    "rspython-ops-catalog-copernicus-s1-aux-infinite/copernicus/s1-aux/",
                ],
                "write_download": [],
            },
            {
                "Version": "2025-01-01",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog",
                        "Condition": {"StringLike": {"s3:prefix": ["copernicus/s1-aux/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-copernicus-s1-aux",
                        "Condition": {"StringLike": {"s3:prefix": ["copernicus/s1-aux/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-copernicus-s1-aux-infinite",
                        "Condition": {"StringLike": {"s3:prefix": ["copernicus/s1-aux/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject"],
                        "Resource": [
                            "arn:aws:s3:::rspython-ops-catalog/copernicus/s1-aux/*",
                            "arn:aws:s3:::rspython-ops-catalog-copernicus-s1-aux/copernicus/s1-aux/*",
                            "arn:aws:s3:::rspython-ops-catalog-copernicus-s1-aux-infinite/copernicus/s1-aux/*",
                        ],
                    },
                ],
            },
        ),
        (
            {
                "read": [],
                "read_download": [],
                "write_download": [
                    "rspython-ops-catalog/copernicus/s1-l1/",
                    "rspython-ops-catalog-copernicus-s1-l1/copernicus/s1-l1/",
                    "rspython-ops-catalog-default-s1-l1/copernicus/s1-l1/",
                ],
            },
            {
                "Version": "2025-01-01",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog",
                        "Condition": {"StringLike": {"s3:prefix": ["copernicus/s1-l1/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-copernicus-s1-l1",
                        "Condition": {"StringLike": {"s3:prefix": ["copernicus/s1-l1/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-default-s1-l1",
                        "Condition": {"StringLike": {"s3:prefix": ["copernicus/s1-l1/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                        "Resource": [
                            "arn:aws:s3:::rspython-ops-catalog/copernicus/s1-l1/*",
                            "arn:aws:s3:::rspython-ops-catalog-copernicus-s1-l1/copernicus/s1-l1/*",
                            "arn:aws:s3:::rspython-ops-catalog-default-s1-l1/copernicus/s1-l1/*",
                        ],
                    },
                ],
            },
        ),
        (
            {
                "read": [
                    "rspython-ops-catalog/*/s1-l1/",
                    "rspython-ops-catalog-copernicus-s1-l1/*/s1-l1/",
                    "rspython-ops-catalog-default-s1-l1/*/s1-l1/",
                ],
                "read_download": [
                    "rspython-ops-catalog/paul/s1-l1/",
                    "rspython-ops-catalog-default-s1-l1/paul/s1-l1/",
                    "rspython-ops-catalog/emilie/*/",
                    "rspython-ops-catalog-emilie-s1-aux-infinite/emilie/*/",
                    "rspython-ops-catalog-default-s1-l1/emilie/*/",
                ],
                "write_download": [
                    "rspython-ops-catalog/paul/s1-l1/",
                    "rspython-ops-catalog-default-s1-l1/paul/s1-l1/",
                ],
            },
            {
                "Version": "2025-01-01",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog",
                        "Condition": {"StringLike": {"s3:prefix": ["*/s1-l1/*", "paul/s1-l1/*", "emilie/*/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-copernicus-s1-l1",
                        "Condition": {"StringLike": {"s3:prefix": ["*/s1-l1/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-default-s1-l1",
                        "Condition": {"StringLike": {"s3:prefix": ["*/s1-l1/*", "paul/s1-l1/*", "emilie/*/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetBucketLocation"],
                        "Resource": [
                            "arn:aws:s3:::rspython-ops-catalog/*",
                            "arn:aws:s3:::rspython-ops-catalog-copernicus-s1-l1/*",
                            "arn:aws:s3:::rspython-ops-catalog-default-s1-l1/*",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-emilie-s1-aux-infinite",
                        "Condition": {"StringLike": {"s3:prefix": ["emilie/*/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject"],
                        "Resource": [
                            "arn:aws:s3:::rspython-ops-catalog/paul/s1-l1/*",
                            "arn:aws:s3:::rspython-ops-catalog-default-s1-l1/paul/s1-l1/*",
                            "arn:aws:s3:::rspython-ops-catalog/emilie/*",
                            "arn:aws:s3:::rspython-ops-catalog-emilie-s1-aux-infinite/emilie/*",
                            "arn:aws:s3:::rspython-ops-catalog-default-s1-l1/emilie/*",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                        "Resource": [
                            "arn:aws:s3:::rspython-ops-catalog/paul/s1-l1/*",
                            "arn:aws:s3:::rspython-ops-catalog-default-s1-l1/paul/s1-l1/*",
                        ],
                    },
                ],
            },
        ),
        (
            {
                "read": [
                    "rspython-ops-catalog-paul/*/*/",
                ],
                "read_download": [],
                "write_download": [],
            },
            {
                "Version": "2025-01-01",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-paul",
                        "Condition": {"StringLike": {"s3:prefix": ["*/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetBucketLocation"],
                        "Resource": [
                            "arn:aws:s3:::rspython-ops-catalog-paul/*",
                        ],
                    },
                ],
            },
        ),
        (
            {
                "read": [
                    "rspython-ops-catalog/no_collection",
                    "rspython-ops-catalog-paul/*/*/",
                ],
                "read_download": [],
                "write_download": [],
            },
            {
                "Version": "2025-01-01",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:ListBucket"],
                        "Resource": "arn:aws:s3:::rspython-ops-catalog-paul",
                        "Condition": {"StringLike": {"s3:prefix": ["*/*"]}},
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["s3:GetBucketLocation"],
                        "Resource": [
                            "arn:aws:s3:::rspython-ops-catalog-paul/*",
                        ],
                    },
                ],
            },
        ),
    ],
)
@patch("rs_server_osam.tasks.datetime")
def test_update_s3_rights_lists(mock_datetime, s3_rights, expected):
    """Test build s3 rights"""
    mock_datetime.now.return_value = datetime(2025, 1, 1)
    assert update_s3_rights_lists(s3_rights) == expected


@pytest.mark.usefixtures("mock_ovh_handler", "mock_keycloak_handler")
class TestCreateObsUser:  # pylint: disable =too-few-public-methods
    """Will be added soon"""

    def __init__(self):
        return


@pytest.mark.usefixtures("mock_ovh_handler", "mock_keycloak_handler")
class TestDeleteObsUser:
    """
    Unit tests for the function `delete_obs_user_account_if_not_used_by_keycloak_account`.

    This test suite verifies that:
    - The function skips deletion if the OBS user description does not contain the expected
      DESCRIPTION_TEMPLATE marker, without %keycloak-user% placehold.
    - No deletion occurs if the OBS user is linked to an existing Keycloak user.
    - The function deletes the OBS user when it is not linked to any Keycloak user and the
      description matches the expected template.
    - No deletion occurs if the OBS user is not linked but the description does not match the template.

    External dependencies like `get_keycloak_user_from_description`, `create_description_from_template`,
    and `get_ovh_handler` are mocked to isolate the function behavior.
    """

    @patch("rs_server_osam.tasks.get_keycloak_user_from_description")
    @patch("rs_server_osam.tasks.create_description_from_template")
    @patch("rs_server_osam.tasks.get_ovh_handler")
    def test_skip_if_not_osam_user(
        self,
        mock_get_ovh_handler,
        mock_create_description,
        mock_get_keycloak_user,
    ):
        """User description does NOT contain DESCRIPTION_TEMPLATE (without %keycloak-user%) → skip deletion"""
        obs_user = {
            "username": "not_osam_user",
            "description": "some unrelated description",
            "id": "obs999",
        }
        with patch("rs_server_osam.utils.tools.DESCRIPTION_TEMPLATE", "## linked to keycloak user %keycloak-user%"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, [])

        mock_get_keycloak_user.assert_not_called()
        mock_create_description.assert_not_called()
        mock_get_ovh_handler.assert_not_called()

    @patch("rs_server_osam.tasks.get_keycloak_user_from_description")
    @patch("rs_server_osam.tasks.get_ovh_handler")
    def test_skip_if_user_created_from_another_platform(
        self,
        mock_get_ovh_handler,
        mock_get_keycloak_user,
    ):
        """User description contains DESCRIPTION_TEMPLATE but contains more info → skip deletion"""
        keycloak_users = [
            {"username": "emilie"},
        ]

        mock_get_keycloak_user.return_value = "paul"
        obs_user = {
            "username": "user_created_from_another_platform",
            "description": "## linked to keycloak user paul from platform XYZ",
            "id": "obs999",
        }
        with patch("rs_server_osam.utils.tools.DESCRIPTION_TEMPLATE", "## linked to keycloak user %keycloak-user%"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)

        mock_get_ovh_handler.assert_not_called()

        with patch(
            "rs_server_osam.utils.tools.DESCRIPTION_TEMPLATE",
            "## linked to keycloak user %keycloak-user% from platform ANOTHER",
        ):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)

        mock_get_ovh_handler.assert_not_called()

    @patch("rs_server_osam.tasks.get_keycloak_user_from_description")
    @patch("rs_server_osam.tasks.create_description_from_template")
    @patch("rs_server_osam.tasks.get_ovh_handler")
    def test_user_linked_to_keycloak_user_no_deletion(
        self,
        mock_get_ovh_handler,
        mock_create_description,
        mock_get_keycloak_user,
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

        with patch("rs_server_osam.utils.tools.DESCRIPTION_TEMPLATE", "## linked to keycloak user %keycloak-user%"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)

        mock_get_keycloak_user.assert_called_once_with(obs_user["description"], template=DESCRIPTION_TEMPLATE)
        mock_create_description.assert_not_called()
        mock_get_ovh_handler.assert_not_called()

    @patch("rs_server_osam.tasks.get_keycloak_user_from_description")
    @patch("rs_server_osam.tasks.create_description_from_template")
    @patch("rs_server_osam.tasks.get_ovh_handler")
    def test_user_not_linked_and_description_matches_deletes(
        self,
        mock_get_ovh_handler,
        mock_create_description,
        mock_get_keycloak_user,
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

        with patch("rs_server_osam.utils.tools.DESCRIPTION_TEMPLATE", "## linked to keycloak user %keycloak-user%"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)

        mock_get_keycloak_user.assert_called_once_with(obs_user["description"], template=DESCRIPTION_TEMPLATE)
        mock_create_description.assert_called_once_with("99999", template=DESCRIPTION_TEMPLATE)
        mock_ovh_handler_instance.delete_user.assert_called_once_with(obs_user["id"])

    @patch("rs_server_osam.tasks.get_keycloak_user_from_description")
    @patch("rs_server_osam.tasks.create_description_from_template")
    @patch("rs_server_osam.tasks.get_ovh_handler")
    def test_user_not_linked_but_description_differs_no_deletion(
        self,
        mock_get_ovh_handler,
        mock_create_description,
        mock_get_keycloak_user,
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

        with patch("rs_server_osam.utils.tools.DESCRIPTION_TEMPLATE", "## linked to keycloak user %keycloak-user%"):
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)

        mock_get_keycloak_user.assert_called_once_with(obs_user["description"], template=DESCRIPTION_TEMPLATE)
        mock_create_description.assert_called_once_with("99999", template=DESCRIPTION_TEMPLATE)
        mock_ovh_handler_instance.delete_user.assert_not_called()


@pytest.mark.parametrize(
    "obs_user_present, access_key_present, raise_exception, expected_result",
    [
        # 1. Success: credentials returned
        (
            True,
            True,
            False,
            {"access_key": "ak123", "secret_key": "sk123", "endpoint": "endpoint123", "region": "region123"},
        ),
        # 2. OBS user found but no access key
        (True, False, False, "Error reading user obs_test from OVH."),
        # 3. OBS user not found
        (False, False, False, "No s3 credentials associated with obs_test"),
        # 4. Exception raised during processing
        (True, True, True, "Simulated failure"),
    ],
    ids=["ok", "ko1", "ko2", "ko3"],
)
@patch("rs_server_osam.tasks.get_ovh_handler")
@patch("rs_server_osam.tasks.get_keycloak_handler")
def test_get_user_s3_credentials(
    mock_get_keycloak_handler,
    mock_get_ovh_handler,
    obs_user_present,
    access_key_present,
    raise_exception,
    expected_result,
    monkeypatch,
):
    """Test cases for get_s3_credentials"""
    monkeypatch.setenv("S3_ENDPOINT", "endpoint123")
    monkeypatch.setenv("S3_REGION", "region123")
    user = "obs_test"

    # Setup mock Keycloak handler
    mock_keycloak_instance = MagicMock()
    mock_keycloak_instance.get_obs_user_from_keycloak_username.return_value = (
        {"id": "obs-user-id", "username": user} if obs_user_present else None
    )
    mock_get_keycloak_handler.return_value = mock_keycloak_instance

    # Setup mock OVH handler
    mock_ovh_instance = MagicMock()
    if obs_user_present and not raise_exception:
        mock_ovh_instance.get_user_s3_access_key.return_value = "ak123" if access_key_present else None
        if access_key_present:
            mock_ovh_instance.get_user_s3_secret_key.return_value = "sk123"
    elif raise_exception:
        mock_ovh_instance.get_user_s3_access_key.side_effect = Exception(expected_result)

    mock_get_ovh_handler.return_value = mock_ovh_instance

    # Nominal case
    if obs_user_present and access_key_present and (not raise_exception):
        result = get_user_s3_credentials(user)
        assert result == expected_result

    # Error cases
    else:
        with pytest.raises(RuntimeError) as e_info:
            get_user_s3_credentials(user)
        assert expected_result == str(e_info.value.__cause__)


@pytest.mark.parametrize(
    "obs_user_present, access_policy, raise_exception, expected_result",
    [
        # 1. Success: access policy applied
        (
            True,
            {"access_policy": "value"},
            False,
            (
                True,
                {"detail": "S3 access policy applied for the OVH account associated with the Keycloak user obs_test"},
            ),
        ),
        # 2. OBS user not found
        (
            False,
            {},
            False,
            (
                False,
                {
                    "detail": "Failed to apply the access policy to the OVH account "
                    "associated with the Keycloak account obs_test. ",
                },
            ),
        ),
        # 3. Exception raised during processing
        (
            True,
            None,
            True,
            (
                False,
                {
                    "detail": "Failed to apply the access policy to the OVH account "
                    "associated with the Keycloak account obs_test. Exception raised",
                },
            ),
        ),
    ],
)
@patch("rs_server_osam.tasks.get_ovh_handler")
@patch("rs_server_osam.tasks.get_keycloak_handler")
def test_apply_user_access_policy(
    mock_get_keycloak_handler,
    mock_get_ovh_handler,
    obs_user_present,
    access_policy,
    raise_exception,
    expected_result,
):
    """Test cases for get_s3_credentials"""
    user = "obs_test"

    # Setup mock Keycloak handler
    mock_keycloak_instance = MagicMock()
    mock_keycloak_instance.get_obs_user_from_keycloak_username.return_value = (
        {"id": "obs-user-id", "username": user} if obs_user_present else None
    )
    mock_get_keycloak_handler.return_value = mock_keycloak_instance

    # Setup mock OVH handler
    mock_ovh_instance = MagicMock()
    if not raise_exception:
        mock_ovh_instance.apply_user_access_policy.return_value = None
    else:
        mock_ovh_instance.apply_user_access_policy.side_effect = BadParametersError("Exception raised")

    mock_get_ovh_handler.return_value = mock_ovh_instance

    result = apply_user_access_policy(user, access_policy)
    assert result == expected_result
