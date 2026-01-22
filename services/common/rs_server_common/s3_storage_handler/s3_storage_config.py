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

"""Functions to get S3 storage settings (bucket name and expiration delay) from CSV configuration file."""

import os

import requests


class S3StorageConfigurationError(Exception):
    """Exception raised when problems occur when retrieving settings from the S3 storage configuration file."""


def fetch_csv_from_endpoint(endpoint: str) -> list[list[str]]:
    """
    Fetches a CSV file from rs-osam endpoint and returns it
    as a list of rows (each row is a list of strings).

    Raises:
        S3StorageConfigurationError: If the endpoint cannot be reached
        or response cannot be parsed as CSV.
    """
    try:
        response = requests.get(endpoint, timeout=10)
        response.raise_for_status()
        data = response.json()  # already list[list[str]]
    except Exception as exc:
        raise S3StorageConfigurationError(
            f"Failed to fetch storage configuration from rs-osam endpoint '{endpoint}': {exc}",
        ) from exc

    if not isinstance(data, list):
        raise S3StorageConfigurationError(
            f"Invalid configuration format returned by rs-osam endpoint: expected list[list[str]], got {type(data)}",
        )

    for row in data:
        if not isinstance(row, list) or not all(isinstance(x, str) for x in row) or len(row) != 5:
            raise S3StorageConfigurationError(
                "Invalid configuration format: expected list[list[str]] containing only strings",
            )

    return data


def get_storage_settings_from_config(
    owner: str,
    collection: str,
    eopf_type: str,
) -> tuple[int, str] | tuple[str, str] | None:
    """
    Fetches the configuration file for the S3 storage from rs-osam
    to extract the correct settings for the parameters given.

    Args:
        owner (str): Owner of the file to upload.
        collection (str): Collection of the file to upload.
        eopf_type (str): 'eopf:type' of the file to upload.
        config_file_path (str, optional): Path to the config file, if None the environment variable will be used.

    Returns:
        tuple: Expiration delay and bucket name for these parameters.
    """
    config_table = fetch_csv_from_endpoint(os.environ["RSPY_HOST_OSAM"] + "/internal/configuration")
    settings = get_settings_from_table(config_table, owner, collection, eopf_type)
    try:
        return (int(settings[0]), settings[1])
    except (ValueError, TypeError):
        # If the settings are not in the expected format we still return what we have to let
        # users handle the possible errors
        return settings


def get_settings_from_table(config_table: list[list], owner: str, collection: str, eopf_type: str):
    """
    Reads CSV table to extract correct settings corresponding to the parameters given.
    Logic used:
        - Try to map the three parameters (owner, collection, eopf:type)
        - If previous step failed, try to map the two parameters (owner, collection)
        - If previous step failed, try to map the two parameters (owner, eopf:type)
        - If previous step failed, use default configuration (STAR,STAR,STAR)

    Args:
        config_table: List of lists representing a CSV table.
        owner (str): Owner of the file to upload.
        collection (str): Collection of the file to upload.
        eopf_type (str): 'eopf:type' of the file to upload.

    Returns:
        tuple: Expiration delay and bucket name for these parameters.

    Raises:
        S3StorageConfigurationError: If the CSV configuration table doesn't have the expected format
                                    (at least 5 columns)
    """
    settings1 = settings2 = settings3 = settings4 = None
    for row in config_table:
        if len(row) < 5:
            raise S3StorageConfigurationError(f"Expected 5 columns in configuration table, got {len(row)}.")
        if row[0:3] == [owner, collection, eopf_type]:
            settings1 = (row[3], row[4])
        if row[0:3] == [owner, collection, "*"]:
            settings2 = (row[3], row[4])
        if row[0:3] == [owner, "*", eopf_type]:
            settings3 = (row[3], row[4])
        if row[0:3] == ["*", "*", "*"]:
            settings4 = (row[3], row[4])
    return settings1 or settings2 or settings3 or settings4


def get_expiration_delay_from_config(owner: str, collection: str, eopf_type: str) -> int:
    """
    Tool function to directly get an expiration delay for a given configuration.

    Args:
        owner (str): Owner of the file to upload.
        collection (str): Collection of the file to upload.
        eopf_type (str): 'eopf:type' of the file to upload.
        config_file_path (str, optional): Path to the config file, if None the environment variable will be used.

    Returns:
        int: Expiration delay (usually in days).

    Raises:
        S3StorageConfigurationError: If the settings retrieved are None or an incorrect format.
    """
    settings = get_storage_settings_from_config(owner, collection, eopf_type)
    if settings is not None and isinstance(settings[0], int):
        return settings[0]
    raise S3StorageConfigurationError(
        f"Could not find expected settings for given configuration (settings retrieved: '{settings}')",
    )


def get_bucket_name_from_config(owner: str, collection: str, eopf_type: str) -> str:
    """
    Tool function to directly get a bucket name for a given configuration.

    Args:
        owner (str): Owner of the file to upload.
        collection (str): Collection of the file to upload.
        eopf_type (str): 'eopf:type' of the file to upload.

    Returns:
        str: Bucket name.

    Raises:
        S3StorageConfigurationError: If the settings retrieved are None or an incorrect format.
    """
    settings = get_storage_settings_from_config(owner, collection, eopf_type)
    if settings is not None and isinstance(settings[1], str):
        return settings[1]
    raise S3StorageConfigurationError(
        f"Could not find expected settings for the given configuration (settings retrieved: '{settings}')",
    )
