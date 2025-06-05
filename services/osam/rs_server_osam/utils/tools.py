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
import logging
import os
from fnmatch import fnmatch

from rs_server_common.s3_storage_handler import s3_storage_config
from rs_server_common.utils.logging import Logging

DEFAULT_CSV_PATH = "/app/conf/expiration_bucket.csv"

logger = Logging.default(__name__)
logger.setLevel(logging.DEBUG)

configmap_data = s3_storage_config.S3StorageConfigurationSingleton().get_s3_bucket_configuration(
    os.environ.get("BUCKET_CONFIG_FILE_PATH", DEFAULT_CSV_PATH),
)


def create_description_from_template(keycloak_user: str, template: str) -> str:
    """Applies the given Keycloak user name in the description, using the given template.
    The template must have a '%keycloak-user%' placeholder.

    Args:
        keycloak_user (str): Keycloak user to set in the description.
        template (str, optionnal): Template to use. Default is '## linked to keycloak user %keycloak-user%'.

    Returns:
        str: Description with correct user name.
    """
    user_placeholder = "%keycloak-user%"
    return template.replace(user_placeholder, keycloak_user)


def get_keycloak_user_from_description(description: str, template: str) -> str:
    """Returns the Keycloak user name included in the given description using its template.
    The template must have a '%keycloak-user%' placeholder.

    Args:
        description (str): Description containing a Keycloak user name.
        template (str, optionnal): Template to use. Default is '## linked to keycloak user %keycloak-user%'.

    Returns:
        str: Keycloak user name.
    """
    user_placeholder = "%keycloak-user%"

    # We use split to handle any case when the placeholder is in the middle of the description
    templates = template.split(user_placeholder)
    for t in templates:
        description = description.replace(t, "")

    return description


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
    matched = set()
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
    records = [rule for rule in configmap_data if rule[0] == user or rule[0] == "*"]
    collections, eopf_type, bucket = zip(*[(r[1], r[2], r[-1]) for r in records]) if records else ([], [], [])
    return list(collections), list(eopf_type), list(bucket)
