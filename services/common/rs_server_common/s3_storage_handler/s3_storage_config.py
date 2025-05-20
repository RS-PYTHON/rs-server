# Copyright 2024 CS Group
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

import csv
import os
import threading

FILEPATH_ENV_VAR = "BUCKET_CONFIG_FILE_PATH"
DEFAULT_FILEPATH = "/app/conf/expiration_bucket.csv"


class S3StorageConfigurationError(Exception):
    """Exception raised when problems occur when retrieving settings from the S3 storage configuration file."""


class S3StorageConfigurationSingleton:
    """Singleton to keep the content of the config file in memory, to avoid excessive I/O operations on the file."""

    def __new__(cls, config_file_path: str = ""):
        if not hasattr(cls, "instance"):
            cls.instance = super().__new__(cls)
            cls.file_lock = threading.Lock()
            cls.bucket_configuration_csv: list[list] = []
            cls.config_file_path: str = ""
            cls.last_config_file_modification_date: float = 0
            if config_file_path:
                cls.load_csv_file_into_variable(config_file_path)
        return cls.instance

    @classmethod
    def load_csv_file_into_variable(cls, config_file_path: str) -> None:
        """
        To load a CSV file into the singleton.
        If the file given is the same one as the one already in the singleton,
        and if this file hasn't changed since last execution, it will do nothing.
        In other cases, it will load the content of the file in the singleton
        and update the file name and modification date values.

        Args:
            config_file_path (str): Path to the config file.
        """
        if (
            cls.config_file_path == config_file_path
            and cls.last_config_file_modification_date
            == cls.get_last_modification_date_of_config_file(config_file_path)
        ):
            return

        data = []
        with open(config_file_path, newline="", encoding="utf-8") as csvfile:
            reader = csv.reader(csvfile, skipinitialspace=True)
            for line in reader:
                data.append(line)

        cls.config_file_path = config_file_path
        cls.last_config_file_modification_date = cls.get_last_modification_date_of_config_file(config_file_path)
        cls.bucket_configuration_csv = data

    @classmethod
    def get_last_modification_date_of_config_file(cls, config_file_path: str) -> float:
        """
        Returns last modification time for given file.

        Args:
            config_file_path (str): Path to the config file.

        Returns:
            str: Last time the file was modificated.
        """
        with cls.file_lock:
            last_modification_time = os.path.getmtime(config_file_path)
        return last_modification_time

    @classmethod
    def get_s3_bucket_configuration(cls, config_file_path: str) -> list[list]:
        """
        Returns content of given CSV configuration file as a table.

        Args:
            config_file_path (str): Path to the CSV config file.

        Returns:
            list[list]: Content of the CSV file.
        """
        cls.load_csv_file_into_variable(config_file_path)
        return cls.bucket_configuration_csv


def get_storage_settings_from_config(
    owner: str,
    collection: str,
    eopf_type: str,
    config_file_path: str = "",
) -> tuple[int, str] | tuple[str, str] | None:
    """
    Reads configuration file for the S3 storage to extract the correct settings for the parameters given.

    Args:
        owner (str): Owner of the file to upload.
        collection (str): Collection of the file to upload.
        eopf_type (str): 'eopf:type' of the file to upload.
        config_file_path (str, optional): Path to the config file, if None the environment variable will be used.

    Returns:
        tuple: Expiration delay and bucket name for these parameters.
    """
    if not config_file_path:
        config_file_path = os.getenv(FILEPATH_ENV_VAR, default=DEFAULT_FILEPATH)
    config_table = S3StorageConfigurationSingleton().get_s3_bucket_configuration(config_file_path)
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


def get_expiration_delay_from_config(owner: str, collection: str, eopf_type: str, config_file_path: str = "") -> int:
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
    settings = get_storage_settings_from_config(owner, collection, eopf_type, config_file_path)
    if settings is not None and isinstance(settings[0], int):
        return settings[0]
    raise S3StorageConfigurationError(
        f"Could not find expected settings for given configuration (settings retrieved: '{settings}')",
    )


def get_bucket_name_from_config(owner: str, collection: str, eopf_type: str, config_file_path: str = "") -> str:
    """
    Tool function to directly get a bucket name for a given configuration.

    Args:
        owner (str): Owner of the file to upload.
        collection (str): Collection of the file to upload.
        eopf_type (str): 'eopf:type' of the file to upload.
        config_file_path (str, optional): Path to the config file, if None the environment variable will be used.

    Returns:
        str: Bucket name.

    Raises:
        S3StorageConfigurationError: If the settings retrieved are None or an incorrect format.
    """
    settings = get_storage_settings_from_config(owner, collection, eopf_type, config_file_path)
    if settings is not None and isinstance(settings[1], str):
        return settings[1]
    raise S3StorageConfigurationError(
        f"Could not find expected settings for given configuration (settings retrieved: '{settings}')",
    )
