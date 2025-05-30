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

"""Main tasks executed by OSAM service."""

import json
import os

# from collections import defaultdict
from fnmatch import fnmatch
from functools import wraps
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from osam.utils.cloud_provider_api_handler import OVHApiHandler
from osam.utils.keycloak_handler import KeycloakHandler
from osam.utils.tools import (
    create_description_from_template,
    get_keycloak_user_from_description,
)
from rs_server_common.s3_storage_handler import s3_storage_config

DEFAULT_DESCRIPTION_TEMPLATE = "## linked to keycloak user %keycloak-user%"
DESCRIPTION_TEMPLATE = os.getenv("OBS_DESCRIPTION_TEMPLATE", default=DEFAULT_DESCRIPTION_TEMPLATE)
DEFAULT_CSV_PATH = "/app/conf/expiration_bucket.csv"

keycloak_handler = KeycloakHandler()
ovh_handler = OVHApiHandler()

configmap_singleton = s3_storage_config.S3StorageConfigurationSingleton()
configmap_data = configmap_singleton.get_s3_bucket_configuration(
    os.environ.get("BUCKET_CONFIG_FILE_PATH", DEFAULT_CSV_PATH),
)
# Setup tracer
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)
span_processor = SimpleSpanProcessor(ConsoleSpanExporter())
trace.get_tracer_provider().add_span_processor(span_processor)  # type: ignore


# Decorator to trace functions
def traced_function(name=None):
    """
    Decorator to trace the execution of a function using OpenTelemetry spans.

    Args:
        name (str, optional): Custom name for the span. Defaults to the function's name.

    Returns:
        Callable: A wrapped function with tracing enabled.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            span_name = name or func.__name__
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("function.name", func.__name__)
                return func(*args, **kwargs)

        return wrapper

    return decorator


def get_allowed_buckets(user: str, csv_rows: list[list[str]]) -> list[str]:
    """Get the allowed buckets for user from the csv configmap"""
    return [rule[-1] for rule in csv_rows if rule[0] == user or rule[0] == "*"]


@traced_function()
def get_keycloak_configmap_values():
    """
    WIP
    """
    kc_users = keycloak_handler.get_keycloak_users()
    user_allowed_buckets = {}
    print(f"CONFIGMAP: {configmap_data}")
    for user in kc_users:
        allowed_buckets = get_allowed_buckets(user["username"], configmap_data)
        print(f"User {user['username']} allowed buckets: {allowed_buckets}")
        user_allowed_buckets[user["username"]] = allowed_buckets
    # ps ps
    return kc_users, user_allowed_buckets


def get_configmap_user_values(user):
    records = [rule for rule in configmap_data if rule[0] == user or rule[0] == "*"]
    collections, eopf_type, bucket = zip(*[(r[1], r[2], r[-1]) for r in records]) if records else ([], [], [])
    return list(collections), list(eopf_type), list(bucket)


def build_users_data_map():
    """
    Builds a dictionary mapping usernames to their associated user data.

    For each user retrieved from Keycloak, this function gathers:
      - Custom attributes from Keycloak
      - Assigned Keycloak roles
      - Associated collections, EOPF types, and buckets from the configmap

    Returns:
        dict: A dictionary where each key is a username and the value is another
              dictionary containing:
                - "keycloak_attribute": Custom user attribute from Keycloak
                - "keycloak_roles": List of roles assigned to the user
                - "collections": List of collections the user has access to
                - "eopf:type": List of EOPF types linked to the user
                - "buckets": List of buckets associated with the user
    """
    users = keycloak_handler.get_keycloak_users()
    return {
        user["username"]: {
            "keycloak_attribute": keycloak_handler.get_obs_user_from_keycloak_user(user),
            "keycloak_roles": [role["name"] for role in keycloak_handler.get_keycloak_user_roles(user["id"])],            
        }
        for user in users
    }


@traced_function()
def link_rspython_users_and_obs_users():
    """
    Coordinates linking between Keycloak users and OVH object storage (OBS) users.

    - Retrieves Keycloak and OBS users.
    - Optionally links or removes users based on whether mappings exist.

    Note:
        The linking/unlinking logic is currently commented out and should be implemented
        based on specific integration rules.
    """

    keycloak_users, _ = get_keycloak_configmap_values()
    try:
        for user in keycloak_users:
            if not keycloak_handler.get_obs_user_from_keycloak_user(user):
                create_obs_user_account_for_keycloak_user(user)

        obs_users = ovh_handler.get_all_users()
        for obs_user in obs_users:
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Exception: {e}")
        print("Continuing anyway")


@traced_function()
def create_obs_user_account_for_keycloak_user(
    keycloak_user: dict,
):
    """
    Creates an OBS user and links it to a Keycloak user.

    Args:
        ovh_handler (OVHApiHandler): Handler to interact with the OVH API.
        keycloak_handler (KeycloakHandler): Handler to interact with Keycloak.
        keycloak_user (dict): A dictionary representing the Keycloak user.

    Returns:
        None
    """
    new_user_description = create_description_from_template(keycloak_user["username"], template=DESCRIPTION_TEMPLATE)
    new_user = ovh_handler.create_user(description=new_user_description)
    keycloak_handler.set_obs_user_in_keycloak_user(keycloak_user, new_user["id"])


@traced_function()
def delete_obs_user_account_if_not_used_by_keycloak_account(
    obs_user: dict,
    keycloak_users: list[dict],
):
    """
    Deletes an OBS user if it is not linked to any Keycloak user.

    Args:
        ovh_handler (OVHApiHandler): Handler to interact with the OVH API.
        obs_user (dict): Dictionary representing the OBS user.
        keycloak_users (list[dict]): List of Keycloak user dictionaries.

    Returns:
        None
    """

    keycloak_user_id = get_keycloak_user_from_description(obs_user["description"], template=DESCRIPTION_TEMPLATE)
    does_user_exist = False
    for keycloak_user in keycloak_users:
        if keycloak_user["id"] == keycloak_user_id:
            does_user_exist = True

    if not does_user_exist:
        # NOTE: this may seem strange considering that we retrieve the keycloak_user_id from
        # get_keycloak_user_from_description, but when the original description doesn't match
        # the template, get_keycloak_user_from_description returns the full description
        expected_description = create_description_from_template(keycloak_user_id, template=DESCRIPTION_TEMPLATE)
        if obs_user["description"] == expected_description:
            ovh_handler.delete_user(obs_user["id"])


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
    except Exception as e:
        print(f"Error parsing role '{role}': {e}")
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


def build_s3_rights(user_info):  # pylint: disable=too-many-locals
    """
    Builds the S3 access rights structure for a user based on their Keycloak roles.

    This function classifies roles into read, write, and download operations, then computes
    the corresponding access rights by matching them against a configmap.

    Args:
        user_info (dict): Dictionary containing user attributes, specifically the "keycloak_roles" key
                          with a list of role strings.

    Returns:
        dict: A dictionary with three keys:
              - "read": List of read-only access paths.
              - "read_download": List of read+download access paths.
              - "write_download": List of write+download access paths.
    """
    # maybe we should use the user id instead of the username ?
    print(f"USER = {user_info}")
    # Step 1: Parse roles
    read_roles = []
    write_roles = []
    download_roles = []

    for role in user_info["keycloak_roles"]:
        parsed = parse_role(role)
        if not parsed:
            continue
        owner, collection, op = parsed
        if op == "read":
            read_roles.append((owner, collection))
        elif op == "write":
            write_roles.append((owner, collection))
        elif op == "download":
            download_roles.append((owner, collection))

    # Step 2-3: Match against configmap
    read_set = match_roles(read_roles)
    write_set = match_roles(write_roles)
    download_set = match_roles(download_roles)

    # Step 3: Merge access
    read_only = read_set - download_set - write_set
    read_download = download_set
    write_download = write_set

    # Step 4: Output
    output = {
        "read": sorted(read_only),
        "read_download": sorted(read_download),
        "write_download": sorted(write_download),
    }

    print(json.dumps(output, indent=2))
    return output
