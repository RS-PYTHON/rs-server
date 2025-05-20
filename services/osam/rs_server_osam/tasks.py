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

from .utils.keycloak_handler import KeycloakHandler
from .utils.cloud_provider_api_handler import OVHApiHandler

# TODO Opentelemetry spans

def link_rspython_users_and_obs_users():

    keycloak_handler = KeycloakHandler()
    ovh_handler = OVHApiHandler()
    keycloak_users = keycloak_handler.get_keycloak_users()

    for user in keycloak_users:
        if not keycloak_handler.get_obs_user_from_keycloak_user(user):
            create_obs_user_account_for_keycloak_user(ovh_handler, keycloak_handler, user)

    obs_users = ovh_handler.get_all_users()
    for obs_user in obs_users:
        delete_obs_user_account_if_not_used_by_keycloak_account(ovh_handler, obs_user, keycloak_users)


def create_obs_user_account_for_keycloak_user(ovh_handler: OVHApiHandler, keycloak_handler: KeycloakHandler, keycloak_user: dict):
    new_user_description = f"## linked to keycloak user {keycloak_user['id']}"
    new_user = ovh_handler.create_user(description=new_user_description)
    keycloak_user = keycloak_handler.set_obs_user_in_keycloak_user(keycloak_user, new_user['id'])
    keycloak_handler.update_keycloak_user(keycloak_user['id'], keycloak_user)


def delete_obs_user_account_if_not_used_by_keycloak_account(ovh_handler: OVHApiHandler, obs_user: dict, keycloak_users: list[dict]):
    keycloak_user_id = obs_user['description'].split()[-1]
    does_user_exist = False
    for keycloak_user in keycloak_users:
        if keycloak_user['id'] == keycloak_user_id:
            does_user_exist = True

    if not does_user_exist:
        ovh_handler.delete_user(obs_user['id'])
