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
import pytest

# pylint: disable = unused-argument
from osam.tasks import (
    build_s3_rights,
    build_users_data_map,
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
        description="## linked to keycloak user test_user_2",
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
    assert "rs-dev-cluster-catalog-test_user_1-bucket" in test_user_1_data[2]
    # Check user_2 allowed buckets.
    test_user_2_data = get_configmap_user_values(TEST_KEYCLOAK_USERS_LIST[1]["username"])
    assert ["test-bucket-default", "test-bucket-fallback-mars-imagery"] in test_user_2_data


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
        # 1. Exact match for alpha and mars-imagery
        (
            [("alpha", "mars-imagery")],
            {
                "test-bucket-alpha-mars-imagery/alpha/mars-imagery/",
                "test-bucket-default/alpha/mars-imagery/",
                "test-bucket-fallback-mars-imagery/alpha/mars-imagery/",
            },
        ),
        # 2. Exact match for alpha and mars-sensors
        (
            [("alpha", "mars-sensors")],
            {
                "test-bucket-alpha-mars-sensors/alpha/mars-sensors/",
                "test-bucket-default/alpha/mars-sensors/",
                "test-bucket-alpha-mars-deepcore/alpha/mars-sensors/",
                "test-bucket-alpha-mars-xray-special/alpha/mars-sensors/",
            },
        ),
        # 3. Exact match on alpha/mars-sensors/xray — only general match applies
        ([("alpha", "xray")], {"test-bucket-default/alpha/xray/"}),
        # 4. Wildcard match: any owner to mars-imagery
        (
            [("random_user", "mars-imagery")],
            {
                "test-bucket-default/random_user/mars-imagery/",
                "test-bucket-fallback-mars-imagery/random_user/mars-imagery/",
            },
        ),
        # 5. Owner-specific: orion with anything
        (
            [("orion", "some-collection")],
            {"test-bucket-orion-prod/orion/some-collection/", "test-bucket-default/orion/some-collection/"},
        ),
        # 6. Owner luna, product doesn’t match ZB_9_PQZ___
        (
            [("luna", "mars-sensors")],
            {
                "test-bucket-default/luna/mars-sensors/",
                "test-bucket-luna-main/luna/mars-sensors/",
                "test-bucket-luna-special-pqz/luna/mars-sensors/",
            },
        ),
        # 7. Multiple roles, all resolved
        (
            [("alpha", "jupiter-data-nrt"), ("alpha", "mars-imagery")],
            {
                "test-bucket-alpha-jupiter-nrt/alpha/jupiter-data-nrt/",
                "test-bucket-default/alpha/jupiter-data-nrt/",
                "test-bucket-alpha-mars-imagery/alpha/mars-imagery/",
                "test-bucket-fallback-mars-imagery/alpha/mars-imagery/",
                "test-bucket-default/alpha/mars-imagery/",
            },
        ),
    ],
)
def test_match_roles(roles, expected):
    """Tests of match_roles, based on input pairs and output roles."""
    assert match_roles(roles) == expected


# match_roles([("alpha", "*")]) = {'test-bucket-alpha-mars-sensors/alpha/*/'}
# match_roles([("beta", "*")]) = {'test-bucket-beta-venus-data/beta/*/'}
# match_roles([("gamma", "*")]) = {'test-bucket-gamma-comet/gamma/*/'}
# match_roles([("delta", "*")]) = {'test-bucket-delta-asteroid/delta/*/'}
@pytest.mark.parametrize(
    "user_info, expected_output",
    [
        (
            # Test 1: user with read and download roles
            {
                "keycloak_roles": [
                    "rs_catalog_alpha:*_read",
                    "rs_catalog_alpha:*_download",
                ],
            },
            {
                "read": [],
                "read_download": sorted(match_roles([("alpha", "*")])),
                "write_download": [],
            },
        ),
        (
            # Test 2: user with write only
            {
                "keycloak_roles": [
                    "rs_catalog_beta:*_write",
                ],
            },
            {
                "read": [],
                "read_download": [],
                "write_download": sorted(match_roles([("beta", "*")])),
            },
        ),
        (
            # Test 3: user with read, write and download mixed
            {
                "keycloak_roles": [
                    "rs_catalog_gamma:*_read",
                    "rs_catalog_gamma:*_write",
                    "rs_catalog_gamma:*_download",
                    "rs_catalog_delta:*_read",
                ],
            },
            {
                "read": sorted(match_roles([("delta", "*")])),
                "read_download": sorted(match_roles([("gamma", "*")])),
                "write_download": sorted(match_roles([("gamma", "*")])),
            },
        ),
        (
            # Test 4: user with invalid role ignored
            {
                "keycloak_roles": [
                    "invalid_role_string",
                    "rs_catalog_alpha:*_read",
                ],
            },
            {
                "read": sorted(match_roles([("alpha", "*")])),
                "read_download": [],
                "write_download": [],
            },
        ),
        (
            # Test 5: empty roles
            {
                "keycloak_roles": [],
            },
            {
                "read": [],
                "read_download": [],
                "write_download": [],
            },
        ),
    ],
)
def test_build_s3_rights(user_info, expected_output):
    """Test build S3 right"""
    result = build_s3_rights(user_info)
    assert result == expected_output
