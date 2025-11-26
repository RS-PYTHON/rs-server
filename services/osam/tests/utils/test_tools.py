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

from osam.utils.tools import (
    S3StorageConfigurationSingleton,
    create_description_from_template,
    get_keycloak_user_from_description,
)

RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / ".." / "resources"
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
