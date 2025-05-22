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

import os
from functools import wraps

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from osam.utils.cloud_provider_api_handler import OVHApiHandler
from osam.utils.keycloak_handler import KeycloakHandler
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3StorageHandler,
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


@traced_function()
def get_keycloak_configmap_values(keycloak_handler: KeycloakHandler):
    """
    WIP
    """
    kc_users = keycloak_handler.get_keycloak_users()
    # ps ps
    return kc_users, None


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
    keycloak_handler = KeycloakHandler()
    ovh_handler = OVHApiHandler()
    keycloak_users, _ = get_keycloak_configmap_values(keycloak_handler)
    try:
        s3_handler = S3StorageHandler(
            os.environ["S3_ACCESSKEY"],
            os.environ["S3_SECRETKEY"],
            os.environ["S3_ENDPOINT"],
            os.environ["S3_REGION"],
        )
    except KeyError as key_exc:
        print(f"KeyError exception in getting the s3 storage handler: {key_exc}")
        return
    s3_handler.disconnect_s3()
    # for user in keycloak_users:
    #    if not keycloak_handler.get_obs_user_from_keycloak_user(user):
    #        create_obs_user_account_for_keycloak_user(ovh_handler, keycloak_handler, user)

    obs_users = ovh_handler.get_all_users()
    # for obs_user in obs_users:
    #    delete_obs_user_account_if_not_used_by_keycloak_account(ovh_handler, obs_user, keycloak_users)


@traced_function()
def create_obs_user_account_for_keycloak_user(
    ovh_handler: OVHApiHandler,
    keycloak_handler: KeycloakHandler,
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
    new_user_description = f"## linked to keycloak user {keycloak_user['id']}"
    new_user = ovh_handler.create_user(description=new_user_description)
    keycloak_user = keycloak_handler.set_obs_user_in_keycloak_user(keycloak_user, new_user["id"])
    keycloak_handler.update_keycloak_user(keycloak_user["id"], keycloak_user)


@traced_function()
def delete_obs_user_account_if_not_used_by_keycloak_account(
    ovh_handler: OVHApiHandler,
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
    keycloak_user_id = obs_user["description"].split()[-1]
    does_user_exist = False
    for keycloak_user in keycloak_users:
        if keycloak_user["id"] == keycloak_user_id:
            does_user_exist = True

    if not does_user_exist:
        ovh_handler.delete_user(obs_user["id"])
