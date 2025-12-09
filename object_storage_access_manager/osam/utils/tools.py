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

"""A collection of varied and versatile utility functions"""
import csv
import logging
import os
import threading
from fnmatch import fnmatch

from rs_server_common.utils.logging import Logging

CSV_PATH_ENV_VAR = "BUCKET_CONFIG_FILE_PATH"
DEFAULT_CSV_PATH = "/app/conf/expiration_bucket.csv"

KEYCLOAK_USER_PLACEHOLDER = "%keycloak-user%"
DEFAULT_DESCRIPTION_TEMPLATE = f"## linked to keycloak user {KEYCLOAK_USER_PLACEHOLDER}"
DESCRIPTION_TEMPLATE = os.getenv("OBS_DESCRIPTION_TEMPLATE", default=DEFAULT_DESCRIPTION_TEMPLATE)
# safeguards for the OBS_DESCRIPTION_TEMPLATE environment variable, in case it is incorrectly set
# or loaded. These checks help prevent potential mistakes of loading the value of this var which may lead
# to the posibility of accidentally deleting all users from OVH.
if not DESCRIPTION_TEMPLATE:
    raise RuntimeError(f"The OBS_DESCRIPTION_TEMPLATE env var is empty. Example: {DEFAULT_DESCRIPTION_TEMPLATE}")
if not DESCRIPTION_TEMPLATE.startswith(DEFAULT_DESCRIPTION_TEMPLATE):
    raise RuntimeError(
        f"Incorect value of OBS_DESCRIPTION_TEMPLATE. It should starts with {DEFAULT_DESCRIPTION_TEMPLATE}. ",
    )
LIST_CHECK_OVH_DESCRIPTION = DESCRIPTION_TEMPLATE.split(KEYCLOAK_USER_PLACEHOLDER)

logger = Logging.default(__name__)
logger.setLevel(logging.DEBUG)


class S3StorageConfigurationSingleton:
    """Singleton to keep the content of the config file in memory, to avoid excessive I/O operations on the file.
    NOTE: We use always the same config file which is bucket_expiration.csv mounted as a configmap.
    """

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
        # import pdb; pdb.set_trace()
        if not os.path.exists(config_file_path):
            raise FileNotFoundError(f"Bucket expiration csv file not found: {config_file_path}")
        # If someone wants to use it with 2 config files, we don't support this. Change the logic here if needed.
        if cls.config_file_path and (cls.config_file_path != config_file_path):
            raise RuntimeError("S3StorageConfigurationSingleton can only manage one config file at a time.")

        if (
            cls.config_file_path == config_file_path
            and cls.last_config_file_modification_date
            == cls.get_last_modification_date_of_config_file(config_file_path)
        ):
            return

        data = []
        try:
            with open(config_file_path, newline="", encoding="utf-8") as csvfile:
                reader = csv.reader(csvfile, skipinitialspace=True)
                for line in reader:
                    data.append(line)
        except Exception as exc:
            raise RuntimeError(f"Error reading bucket expiration csv file {config_file_path}: {exc}") from exc

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


def load_configmap_data():
    """Loads the configmap data from the CSV file specified in the environment variable or default path.

    Returns:
        list[list]: Content of the CSV file as a list of rows.
    """
    try:
        return S3StorageConfigurationSingleton().get_s3_bucket_configuration(
            os.environ.get(CSV_PATH_ENV_VAR, DEFAULT_CSV_PATH),
        )
    except FileNotFoundError as e:
        logger.error(f"Configmap CSV file not found: {e}")
        return None
    except RuntimeError as e:
        logger.error(f"Error loading configmap CSV file: {e}")
        return None


# Should this be read once and that's it?  Or should it be re-read each time to catch updates?
# If latter, we should wrap it in each function that calls it:
# - match_roles
# - get_configmap_user_values
# configmap_data = S3StorageConfigurationSingleton().get_s3_bucket_configuration(
#     os.environ.get(CSV_PATH_ENV_VAR, DEFAULT_CSV_PATH),
# )


def create_description_from_template(keycloak_user: str, template: str) -> str:
    """Applies the given Keycloak user name in the description, using the given template.
    The template must have a '%keycloak-user%' placeholder.

    Args:
        keycloak_user (str): Keycloak user to set in the description.
        template (str, optionnal): Template to use. Default is '## linked to keycloak user %keycloak-user%'.

    Returns:
        str: Description with correct user name.
    """
    return template.replace(KEYCLOAK_USER_PLACEHOLDER, keycloak_user)


def get_keycloak_user_from_description(description: str, template: str) -> str | None:
    """Returns the Keycloak user name included in the given description using its template.
    The template must have a '%keycloak-user%' placeholder.

    Args:
        description (str): Description containing a Keycloak user name.
        template (str, optionnal): Template to use. Default is '## linked to keycloak user %keycloak-user%'.

    Returns:
        str | None: Keycloak user name or None if the conditions are not fulfilled
    """
    prefix = template.split(KEYCLOAK_USER_PLACEHOLDER)[0]
    description = description.strip()
    logger.debug(f"prefix from template = {prefix}")
    logger.debug(f"ovh description = {description}")
    if description.startswith(prefix.strip()):
        username = description[len(prefix) :].split(" ", 1)[0]  # noqa
        return username.strip()
    return None


def parse_role(role):
    """
    Parses a Keycloak role string into owner, collection, and operation components.

    This function expects the role to follow the format: `<prefix>_<owner>:<collection>_<operation>`.
    It extracts and returns the owner, collection name, and operation (e.g., read, write, download).

    Args:
        role (str): Role string to be parsed.

    Returns:
        tuple[str, str, str] | None: A tuple (owner, collection, operation) if parsing is successful;
                                     otherwise, returns None on format error or exception.
    """
    try:
        lhs, rhs = role.split(":")
        # Split the left part from the last underscore to get owner
        process_owner_split = lhs.rsplit("_", 1)
        if len(process_owner_split) != 2:
            return None
        owner = process_owner_split[1]

        # Right side is collection_operation
        if "_" not in rhs:
            return None
        collection, op = rhs.rsplit("_", 1)
        return owner.strip(), collection.strip(), op.lower().strip()
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning(f"Error parsing role '{role}': {e}")
        return None


def match_roles(roles):
    """
    Matches parsed roles against a configuration map to determine S3 bucket access paths.

    Args:
        roles (list[tuple[str, str]]): List of tuples representing (owner, collection) pairs
                                       from parsed user roles.

    Returns:
        set[str]: Set of S3 access paths that match the given roles based on wildcards and
                  configmap entries.
    """
    matched: set[str] = set()
    configmap_data = load_configmap_data()
    if configmap_data is None:
        return matched

    for role_owner, role_collection in roles:
        for cfg_owner, cfg_collection, _, _, bucket in configmap_data:
            owner_match = role_owner == "*" or cfg_owner == "*" or fnmatch(cfg_owner.strip(), role_owner)
            collection_match = (
                role_collection == "*" or cfg_collection == "*" or fnmatch(cfg_collection.strip(), role_collection)
            )
            if owner_match and collection_match:
                matched.add(f"{bucket.strip()}/{role_owner.strip()}/{role_collection.strip()}/")
    return matched


def get_allowed_buckets(user: str, csv_rows: list[list[str]]) -> list[str]:
    """Get the allowed buckets for user from the csv configmap"""
    return [rule[-1] for rule in csv_rows if rule[0] == user or rule[0] == "*"]


def get_configmap_user_values(user):
    """
    Retrieves collection, eopf_type, and bucket access values for a given user
    based on rules defined in the `configmap_data`.

    The function filters `configmap_data` entries where the first element
    (the user specifier) matches the provided `user` or the wildcard `"*"`.
    It then extracts and groups the second, third, and last values from the matching rules.

    Args:
        user (str): The username to look up in the configmap rules.

    Returns:
        tuple[list, list, list]: Three lists corresponding to:
            - collections (list): Values from the second element in matched rules.
            - eopf_type (list): Values from the third element in matched rules.
            - bucket (list): Values from the last element in matched rules.
    """
    configmap_data = load_configmap_data()
    if configmap_data is None:
        return [], [], []
    records = [rule for rule in configmap_data if rule[0] == user or rule[0] == "*"]
    collections, eopf_type, bucket = zip(*[(r[1], r[2], r[-1]) for r in records]) if records else ([], [], [])
    return list(collections), list(eopf_type), list(bucket)
