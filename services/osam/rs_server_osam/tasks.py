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

import os
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
            "collections": (cfgmap_data := get_configmap_user_values(user["username"]))[0],
            "eopf_type": cfgmap_data[1],
            "buckets": cfgmap_data[2],
        }
        for user in users
    }


def build_s3_rights(user_info):
    """
    Get the OBS access rights to be set for each RS user
    """
    # maybe we should use the user id instead of the username ?
    print(f"USER = {user_info}")


    


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

    keycloak_users, user_allowed_buckets = get_keycloak_configmap_values()
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
