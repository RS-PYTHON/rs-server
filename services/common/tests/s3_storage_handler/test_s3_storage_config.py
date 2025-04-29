"""Unit tests for s3_storage_config functions."""

import os
from pathlib import Path

import pytest
import rs_server_common.s3_storage_handler.s3_storage_config as s3_storage_config

RESOURCES_FOLDER = Path(os.path.realpath(os.path.dirname(__file__))) / ".." / "testresources"
S3_EXPIRATION_BUCKET_CSV_FILE = os.path.join(RESOURCES_FOLDER, "expiration_bucket.csv")
EMPTY_S3_EXPIRATION_BUCKET_CSV_FILE = os.path.join(RESOURCES_FOLDER, "empty_expiration_bucket.csv")


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
    # Setting up correct env var
    os.environ["BUCKET_CONFIG_FILE_PATH"] = EMPTY_S3_EXPIRATION_BUCKET_CSV_FILE

    owner_name = "titi"
    collection_name = "tata"
    eopf_type = "toto"

    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.get_expiration_delay_from_config(owner_name, collection_name, eopf_type)
    with pytest.raises(s3_storage_config.S3StorageConfigurationError):
        s3_storage_config.get_bucket_name_from_config(owner_name, collection_name, eopf_type)
