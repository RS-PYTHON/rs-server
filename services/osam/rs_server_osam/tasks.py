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
import logging
import os
from functools import wraps

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from osam.utils.cloud_provider_api_handler import OVHApiHandler
from osam.utils.keycloak_handler import KeycloakHandler
from osam.utils.tools import (
    DEFAULT_CSV_PATH,
    create_description_from_template,
    get_allowed_buckets,
    get_keycloak_user_from_description,
    match_roles,
    parse_role,
)
from rs_server_common.s3_storage_handler import s3_storage_config
from rs_server_common.utils.logging import Logging

DEFAULT_DESCRIPTION_TEMPLATE = "## linked to keycloak user %keycloak-user%"
DESCRIPTION_TEMPLATE = os.getenv("OBS_DESCRIPTION_TEMPLATE", default=DEFAULT_DESCRIPTION_TEMPLATE)
OVH_ROLE_FOR_NEW_USERS = "objectstore_operator"

logger = Logging.default(__name__)
logger.setLevel(logging.DEBUG)

configmap_data = s3_storage_config.S3StorageConfigurationSingleton().get_s3_bucket_configuration(
    os.environ.get("BUCKET_CONFIG_FILE_PATH", DEFAULT_CSV_PATH),
)
# Setup tracer
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)
span_processor = SimpleSpanProcessor(ConsoleSpanExporter())
trace.get_tracer_provider().add_span_processor(span_processor)  # type: ignore


# Get keycloak/ovh handler (it doesn't creates duplicates)
def get_keycloak_handler():
    """Used to get a copy of Keycloak handler"""
    return KeycloakHandler()


def get_ovh_handler():
    """Used to get a copy of Ovh handler"""
    return OVHApiHandler()


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


@traced_function()
def get_keycloak_configmap_values():
    """
    Retrieves all Keycloak users and computes the list of allowed S3 buckets
    for each user based on a predefined ConfigMap.

    Returns:
        tuple: A tuple containing:
            - kc_users (list): List of Keycloak user dictionaries.
            - user_allowed_buckets (dict): A mapping of usernames to lists of allowed buckets.
    """
    kc_users = get_keycloak_handler().get_keycloak_users()
    user_allowed_buckets = {}
    for user in kc_users:
        allowed_buckets = get_allowed_buckets(user["username"], configmap_data)
        logger.debug(f"User {user['username']} allowed buckets: {allowed_buckets}")
        user_allowed_buckets[user["username"]] = allowed_buckets
    # ps ps
    return kc_users, user_allowed_buckets


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
    users = get_keycloak_handler().get_keycloak_users()
    return {
        user["username"]: {
            "keycloak_attribute": get_keycloak_handler().get_obs_user_from_keycloak_user(user),
            "keycloak_roles": [role["name"] for role in get_keycloak_handler().get_keycloak_user_roles(user["id"])],
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

    keycloak_users = get_keycloak_handler().get_keycloak_users()
    try:
        # Iterate keycloak users and create an cloud provider account if missing
        for user in keycloak_users:
            if not get_keycloak_handler().get_obs_user_from_keycloak_user(user):
                create_obs_user_account_for_keycloak_user(user)

        # Get the updated keycloak users and cloud provider users
        keycloak_users = get_keycloak_handler().get_keycloak_users()
        obs_users = get_ovh_handler().get_all_users()
        for obs_user in obs_users:
            # If the cloud provider user is not linked with a keycloak account, remove it.
            delete_obs_user_account_if_not_used_by_keycloak_account(obs_user, keycloak_users)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception(f"Exception: {e}")
        raise RuntimeError(f"Exception: {e}") from e


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
    new_user = get_ovh_handler().create_user(description=new_user_description, role=OVH_ROLE_FOR_NEW_USERS)
    get_keycloak_handler().set_obs_user_in_keycloak_user(keycloak_user, new_user["id"])


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
    if DESCRIPTION_TEMPLATE.replace("%keycloak-user%", "") not in obs_user["description"]:
        logger.info(f"The ovh user {obs_user['username']} is not created by osam service. Skipping....")
        return
    keycloak_user_id = get_keycloak_user_from_description(obs_user["description"], template=DESCRIPTION_TEMPLATE)
    logger.debug(f"user: {obs_user}")
    logger.debug(f"keycloak_user_id = {keycloak_user_id}")
    does_user_exist = False
    for keycloak_user in keycloak_users:
        logger.debug(f"keycloak_user = {keycloak_user['username']}")
        if keycloak_user["username"] == keycloak_user_id:
            does_user_exist = True

    if not does_user_exist:
        # NOTE: this may seem strange considering that we retrieve the keycloak_user_id from
        # get_keycloak_user_from_description, but when the original description doesn't match
        # the template, get_keycloak_user_from_description returns the full description
        expected_description = create_description_from_template(keycloak_user_id, template=DESCRIPTION_TEMPLATE)
        if obs_user["description"] == expected_description:
            logger.info(f"Removal of the OVH user {obs_user['username']} with id {obs_user['id']}")
            get_ovh_handler().delete_user(obs_user["id"])


def get_user_s3_credentials(user: str):
    """
    Retrieves the S3 access and secret keys for a given user.

    Args:
        user (str): The username for whom to retrieve S3 credentials.

    Returns:
        dict: A dictionary containing the 'access_key' and 'secret_key' for the user's S3 storage.
    """
    obs_user = get_keycloak_handler().get_obs_user_from_keycloak_username(user)
    if access_key := get_ovh_handler().get_user_s3_access_key(obs_user):
        secret_key = get_ovh_handler().get_user_s3_secret_key(obs_user, access_key)
        return {"access_key": access_key, "secret_key": secret_key}
    return {"detail": f"No s3 credentials associated with {user}"}


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

    logger.info(json.dumps(output, indent=2))
    return output
