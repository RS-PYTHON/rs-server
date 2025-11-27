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

"""Test file for tools functions."""
import os
import os.path as osp
from pathlib import Path
from unittest.mock import patch

import pytest
from osam.utils.tools import (
    CSV_PATH_ENV_VAR,
    S3StorageConfigurationSingleton,
    create_description_from_template,
    get_configmap_user_values,
    get_keycloak_user_from_description,
    load_configmap_data,
    match_roles,
    parse_role,
)

from .conftest import TEST_KEYCLOAK_USERS_LIST

RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / "resources"
S3_EXPIRATION_BUCKET_CSV_FILE = os.path.join(RESOURCES_FOLDER, "expiration_bucket.csv")
EMPTY_S3_EXPIRATION_BUCKET_CSV_FILE = os.path.join(RESOURCES_FOLDER, "empty_expiration_bucket.csv")


def test_singleton():
    """Test if singleton works properly"""
    singleton = S3StorageConfigurationSingleton()
    singleton_instance_2 = S3StorageConfigurationSingleton()
    assert singleton is singleton_instance_2
    assert not singleton.config_file_path
    assert not singleton.bucket_configuration_csv
    assert singleton.last_config_file_modification_date == 0

    singleton.get_s3_bucket_configuration(S3_EXPIRATION_BUCKET_CSV_FILE)
    assert singleton.config_file_path == S3_EXPIRATION_BUCKET_CSV_FILE
    assert singleton.bucket_configuration_csv
    assert singleton.last_config_file_modification_date == singleton.get_last_modification_date_of_config_file(
        S3_EXPIRATION_BUCKET_CSV_FILE,
    )

    singleton.get_s3_bucket_configuration(EMPTY_S3_EXPIRATION_BUCKET_CSV_FILE)
    assert singleton.config_file_path == EMPTY_S3_EXPIRATION_BUCKET_CSV_FILE
    assert not singleton.bucket_configuration_csv
    assert singleton.last_config_file_modification_date == singleton.get_last_modification_date_of_config_file(
        EMPTY_S3_EXPIRATION_BUCKET_CSV_FILE,
    )


def test_singleton_new_with_config_file_path():
    """Test that __new__ loads the file when config_file_path is provided."""
    test_csv = str(RESOURCES_FOLDER / "expiration_bucket.csv")

    # if config_file_path: -> loads the file
    singleton = S3StorageConfigurationSingleton(config_file_path=test_csv)

    # verify the file was actually loaded
    assert singleton.bucket_configuration_csv
    assert singleton.config_file_path == test_csv
    assert singleton.last_config_file_modification_date > 0
    assert len(singleton.bucket_configuration_csv) >= 1  # at least header or data

    # verify it's still a singleton
    singleton2 = S3StorageConfigurationSingleton()  # no path
    assert singleton is singleton2
    assert singleton2.config_file_path == test_csv  # still loaded


def test_load_csv_file_into_variable_file_not_found():
    """Test that FileNotFoundError is raised when CSV file does not exist."""
    singleton = S3StorageConfigurationSingleton()
    fake_path = "/fake/path/expiration_bucket.csv"

    with pytest.raises(FileNotFoundError) as exc_info:
        singleton.load_csv_file_into_variable(fake_path)

    assert str(exc_info.value) == f"Bucket expiration csv file not found: {fake_path}"
    # state should remain unchanged (or empty if first load)
    # but since we never loaded a real file before, config_file_path should still be ""
    assert singleton.config_file_path == "" or not singleton.config_file_path


@patch("builtins.open")
def test_load_csv_file_into_variable_file_open_failure(mock_open):
    """
    Test that RuntimeError is raised (and properly chained) when the file exists
    but cannot be read (covers the 'except Exception as exc:' block).
    """
    singleton = S3StorageConfigurationSingleton()
    test_csv = str(RESOURCES_FOLDER / "expiration_bucket.csv")
    mock_open.side_effect = PermissionError("Fake permission denied")
    with pytest.raises(RuntimeError) as exc_info:
        singleton.load_csv_file_into_variable(test_csv)

    assert "Error reading bucket expiration csv file" in str(exc_info.value)
    assert test_csv in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, PermissionError)


def test_get_configmap_user_values():
    """Test values received from configmap based on user."""
    # Check user_1 allowed buckets.
    test_user_1_data = get_configmap_user_values(TEST_KEYCLOAK_USERS_LIST[0]["username"])
    assert "rspython-ops-catalog-paul" in test_user_1_data[2]
    # Check user_2 allowed buckets.
    test_user_2_data = get_configmap_user_values(TEST_KEYCLOAK_USERS_LIST[1]["username"])
    assert "rspython-ops-catalog" in test_user_2_data[2]
    assert "rspython-ops-catalog-emilie-s1-aux-infinite" in test_user_2_data[2]


def test_load_configmap_data_success(monkeypatch):
    """Test if the real test CSV file exists and that it returns the parsed content."""
    monkeypatch.setenv(CSV_PATH_ENV_VAR, S3_EXPIRATION_BUCKET_CSV_FILE)

    # directly load from the real test file path
    result = load_configmap_data()

    expected_rows = [
        ["*", "*", "*", "100", "rspython-ops-catalog"],
        ["copernicus", "s1-l1", "*", "100", "rspython-ops-catalog-copernicus-s1-l1"],
        ["copernicus", "s1-aux", "*", "100", "rspython-ops-catalog-copernicus-s1-aux"],
        ["copernicus", "s1-aux", "orbsct", "100", "rspython-ops-catalog-copernicus-s1-aux-infinite"],
        ["emilie", "s1-aux", "obmemc", "100", "rspython-ops-catalog-emilie-s1-aux-infinite"],
        ["paul", "*", "*", "100", "rspython-ops-catalog-paul"],
        ["emilie", "*", "*", "100", "rspython-ops-catalog"],
        ["*", "s1-l1", "*", "100", "rspython-ops-catalog-default-s1-l1"],
    ]

    assert result == expected_rows
    assert len(result) == 8
    assert result[0][4] == "rspython-ops-catalog"
    assert any(row[0] == "paul" for row in result)


def test_load_configmap_data_file_not_found(monkeypatch):
    """File not found, it logs error and returns None."""
    fake_path = "/fake/path/config.csv"
    monkeypatch.setenv(CSV_PATH_ENV_VAR, fake_path)

    # Make the singleton raise FileNotFoundError when trying to load
    with patch.object(
        S3StorageConfigurationSingleton,
        "get_s3_bucket_configuration",
        side_effect=FileNotFoundError(f"Bucket expiration csv file not found: {fake_path}"),
    ):
        assert load_configmap_data() is None


def test_load_configmap_data_runtime_error_returns_none():
    """RuntimeError during load -> returns None."""
    with patch.object(
        S3StorageConfigurationSingleton,
        "get_s3_bucket_configuration",
        side_effect=RuntimeError("Failed to parse CSV"),
    ):
        assert load_configmap_data() is None


def test_load_configmap_data_uses_env_var_when_set(monkeypatch):
    """Respects BUCKET_CONFIG_FILE_PATH env var."""
    custom_path = "/custom/config.csv"
    monkeypatch.setenv(CSV_PATH_ENV_VAR, custom_path)

    with patch.object(S3StorageConfigurationSingleton, "get_s3_bucket_configuration") as mock_get:
        mock_get.return_value = [["*", "*", "*", "100", "bucket"]]
        load_configmap_data()
        mock_get.assert_called_once_with(custom_path)


def test_load_configmap_data_uses_default_path_when_env_not_set(monkeypatch):
    """Critical fix: patch DEFAULT_CSV_PATH to use real test file."""
    monkeypatch.delenv(CSV_PATH_ENV_VAR, raising=False)

    with patch("osam.utils.tools.DEFAULT_CSV_PATH", S3_EXPIRATION_BUCKET_CSV_FILE):
        with patch.object(S3StorageConfigurationSingleton, "get_s3_bucket_configuration") as mock_get:
            mock_get.return_value = []
            load_configmap_data()
            mock_get.assert_called_once_with(S3_EXPIRATION_BUCKET_CSV_FILE)


def test_create_description_from_template():
    """Test for create_description_from_template"""

    test_template = "Test template user name: %keycloak-user%"
    test_user = "copernicus"
    test_description = create_description_from_template(test_user, test_template)
    assert test_description == "Test template user name: copernicus"


def test_get_keycloak_user_from_description():
    """Test for get_keycloak_user_from_description"""

    test_template_1 = "Test template user name: %keycloak-user%"
    test_description_1 = "Test template user name: copernicus"
    test_user_1 = get_keycloak_user_from_description(test_description_1, test_template_1)
    assert test_user_1 == "copernicus"

    test_template_2 = "Test template for user name %keycloak-user% but in the middle of a sentence"
    test_description_2 = "Test template for user name copernicus but in the middle of a sentence"
    test_user_2 = get_keycloak_user_from_description(test_description_2, test_template_2)
    assert test_user_2 == "copernicus"


def test_get_keycloak_user_from_description_returns_none_when_prefix_mismatch():
    """Test that None is returned when the description does not start with the expected prefix"""
    template = "## linked to keycloak user %keycloak-user%"
    description = "A totally different description without the prefix"

    result = get_keycloak_user_from_description(description, template)

    assert result is None


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


def test_parse_role_returns_none_when_no_underscore_in_lhs():
    """Make sonarqube happy:
    Covers: if len(process_owner_split) != 2 -> return None
    """
    # no underscore at all in left part
    assert parse_role("rscatalogpauls1l1_read") is None
    assert parse_role("invalidformat:s1-l1_read") is None


def test_parse_role_returns_none_when_no_underscore_in_rhs():
    """Make sonarqube happy:
    Covers: if "_" not in rhs → return None
    """
    # right side has no underscore -> cannot split collection_operation
    assert parse_role("rs_catalog_paul:s1l1read") is None
    assert parse_role("rs_catalog_paul:read") is None
    assert parse_role("rs_catalog_paul:s1-l1-") is None
    assert parse_role("rs_catalog_paul:") is None  # empty rhs


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


@patch("osam.utils.tools.load_configmap_data", return_value=None)
def test_match_roles_and_get_configmap_user_values_handle_missing_configmap(mock_load):
    """
    Test that both functions gracefully handle a missing or unreadable configmap CSV file
    by returning empty results when load_configmap_data() returns None.
    This covers both early return paths and makes sonarqube happy as well...
    """
    # Test match_roles
    roles_to_match = [("paul", "s1-l1"), ("emilie", "*")]
    result = match_roles(roles_to_match)
    assert result == set()  # empty set
    assert mock_load.called

    # Test get_configmap_user_values
    collections, eopf_types, buckets = get_configmap_user_values("paul")
    assert not collections
    assert not eopf_types
    assert not buckets
    assert mock_load.called  # called again (or same call count)

    # Verify load_configmap_data was called exactly twice (once per function)
    assert mock_load.call_count == 2
