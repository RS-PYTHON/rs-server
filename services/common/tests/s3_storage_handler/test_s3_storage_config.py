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

"""Unit tests for s3_storage_config functions."""

import os

import pytest
from rs_server_common.s3_storage_handler import s3_storage_config

from .helpers import RESOURCES_FOLDER

S3_EXPIRATION_BUCKET_CSV_FILE = os.path.join(RESOURCES_FOLDER, "expiration_bucket.csv")
EMPTY_S3_EXPIRATION_BUCKET_CSV_FILE = os.path.join(RESOURCES_FOLDER, "empty_expiration_bucket.csv")


def test_singleton():
    """Test if singleton works properly"""
    singleton = s3_storage_config.S3StorageConfigurationSingleton()
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


def test_get_settings_with_correct_inputs():
    """Test for correct use"""
    # Setting up correct env var
    os.environ["BUCKET_CONFIG_FILE_PATH"] = S3_EXPIRATION_BUCKET_CSV_FILE

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


def test_errors_when_config_file_empty():
    """Test of errors throwing for one specific failing case"""
    empty_config_file = EMPTY_S3_EXPIRATION_BUCKET_CSV_FILE

    owner_name = "titi"
    collection_name = "tata"
    eopf_type = "toto"

    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.get_expiration_delay_from_config(owner_name, collection_name, eopf_type, empty_config_file)
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.get_bucket_name_from_config(owner_name, collection_name, eopf_type, empty_config_file)
