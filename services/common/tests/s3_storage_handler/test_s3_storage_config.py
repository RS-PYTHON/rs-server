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

"""Unit tests for s3_storage_config functions."""

import pytest
from rs_server_common.s3_storage_handler import s3_storage_config


def test_fetch_csv_success(_mock_get_success):
    """
    Tests that fetch_csv_from_endpoint successfully parses a valid CSV response.

    This test uses a mocked successful http get request that returns a well-formed
    csv payload encoded as JSON. The function is expected to:

    - correctly parse the CSV rows,
    - return a list of lists,
    - preserve field order,
    - contain the expected number of rows.
    """
    result = s3_storage_config.fetch_csv_from_endpoint("https://dummy-osam")
    assert len(result) == 4
    assert result[0] == ["*", "*", "*", "30", "rspython-ops-catalog-all-production"]


def test_fetch_csv_network_error(_mock_get_network_error):
    """
    Tests that network-related failures are converted into S3StorageConfigurationError.
    """
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.fetch_csv_from_endpoint("https://dummy-osam")


def test_fetch_csv_invalid_json(_mock_get_invalid_json):
    """
    Tests the behavior when the get response JSON cannot be decoded.
    """
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.fetch_csv_from_endpoint("https://dummy-osam")


def test_fetch_csv_row_not_list(_mock_get_row_not_list):
    """
    Tests handling of rows that are not lists inside the returned JSON payload.
    """
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.fetch_csv_from_endpoint("https://dummy-osam")


def test_fetch_csv_non_string(_mock_get_non_string):
    """
    Tests validation of non-string fields inside CSV rows.
    """
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.fetch_csv_from_endpoint("https://dummy-osam")


def test_fetch_csv_row_wrong_length_too_short(_mock_get_row_wrong_length_too_short):
    """
    Tests handling of CSV rows that contain fewer than the required 5 fields.
    """
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.fetch_csv_from_endpoint("https://dummy-osam")


def test_fetch_csv_row_wrong_length_too_long(_mock_get_row_wrong_length_too_long):
    """
    Tests handling of CSV rows that contain more than the required 5 fields.
    """
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.fetch_csv_from_endpoint("https://dummy-osam")


def test_get_settings_with_correct_inputs(_mock_os_env, _mock_get_success):
    """Test for correct use"""
    # Inputs 1
    owner_name = "copernicus"
    collection_name = "s1-aux"
    eopf_type = "orbsct"
    assert s3_storage_config.get_expiration_delay_from_config(owner_name, collection_name, eopf_type) == 7300
    assert (
        s3_storage_config.get_bucket_name_from_config(owner_name, collection_name, eopf_type)
        == "rspython-ops-catalog-copernicus-s1-aux-infinite"
    )

    # Inputs 2
    owner_name = "copernicus"
    collection_name = "s1-aux"
    eopf_type = "toto"
    assert s3_storage_config.get_expiration_delay_from_config(owner_name, collection_name, eopf_type) == 40
    assert (
        s3_storage_config.get_bucket_name_from_config(owner_name, collection_name, eopf_type)
        == "rspython-ops-catalog-copernicus-s1-aux"
    )

    # Inputs 3
    owner_name = "titi"
    collection_name = "tata"
    eopf_type = "toto"
    assert s3_storage_config.get_expiration_delay_from_config(owner_name, collection_name, eopf_type) == 30
    assert (
        s3_storage_config.get_bucket_name_from_config(owner_name, collection_name, eopf_type)
        == "rspython-ops-catalog-all-production"
    )


def test_errors_when_osam_endpoint_fails(_mock_os_env):
    """Test of errors throwing for one specific failing case
    The requests.get is not mocked anymore, so fetch_csv_from_endpoint will fail
    because there is no real OSAM endpoint at the given URL.
    """

    owner_name = "titi"
    collection_name = "tata"
    eopf_type = "toto"

    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.get_expiration_delay_from_config(owner_name, collection_name, eopf_type)
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.get_bucket_name_from_config(owner_name, collection_name, eopf_type)


def test_get_settings_from_table_exact_match():
    """
    Returns the correct result when an exact match exists for owner, collection, and eopf_type.
    The first row matches all three fields exactly, so the function should
    immediately return the associated expiration value and bucket name.
    """
    table = [
        ["copernicus", "s1-aux", "orbsct", "7300", "bucket-exact"],
        ["copernicus", "s1-aux", "*", "40", "bucket-collection"],
        ["copernicus", "*", "orbsct", "111", "bucket-eopf"],
        ["*", "*", "*", "30", "bucket-default"],
    ]

    result = s3_storage_config.get_settings_from_table(
        table,
        owner="copernicus",
        collection="s1-aux",
        eopf_type="orbsct",
    )
    assert result == ("7300", "bucket-exact")


def test_get_settings_from_table_owner_collection_fallback():
    """
    Fallback logic when owner and collection match but eopf_type does not.
    The table has no exact match for all three fields, but contains a row where
    the owner and collection match and eopf_type is '*'. This row should be returned.
    """
    table = [
        ["copernicus", "s1-aux", "*", "40", "bucket-collection"],
        ["copernicus", "*", "orbsct", "999", "bucket-eopf"],
        ["*", "*", "*", "30", "bucket-default"],
    ]

    result = s3_storage_config.get_settings_from_table(
        table,
        owner="copernicus",
        collection="s1-aux",
        eopf_type="nonexisting",
    )
    assert result == ("40", "bucket-collection")


def test_get_settings_from_table_owner_eopf_fallback():
    """
    Fallback logic when owner and eopf_type match but collection does not.

    In this case the function should return the row with the matching owner
    and eopf_type and wildcard collection.
    """
    table = [
        ["copernicus", "*", "orbsct", "111", "bucket-eopf"],
        ["*", "*", "*", "30", "bucket-default"],
    ]

    result = s3_storage_config.get_settings_from_table(
        table,
        owner="copernicus",
        collection="notfound",
        eopf_type="orbsct",
    )
    assert result == ("111", "bucket-eopf")


def test_get_settings_from_table_invalid_row_length():
    """
    Tests that a malformed table row (fewer than 5 columns) raises an error.

    A valid configmap row must contain exactly 5 fields. Any row with an invalid
    structure must trigger S3StorageConfigurationError.
    """
    table = [["a", "b", "c"]]  # < 5 items

    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.get_settings_from_table(
            table,
            owner="a",
            collection="b",
            eopf_type="c",
        )
