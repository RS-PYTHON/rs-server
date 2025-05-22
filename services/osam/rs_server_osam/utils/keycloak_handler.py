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

import logging
import os
from typing import Any

from keycloak import KeycloakAdmin, KeycloakError, KeycloakOpenIDConnection

logger = logging.getLogger(__name__)


class KeycloakHandler:

    def __init__(self) -> None:
        self.keycloak_admin = self.__open_keycloak_connection()

    def __open_keycloak_connection(self) -> KeycloakAdmin:

        server_url = os.environ["OIDC_ENDPOINT"]
        realm_name = os.environ["OIDC_REALM"]
        client_id = os.environ["OIDC_CLIENT_ID"]
        client_secret_key = os.environ["OIDC_CLIENT_SECRET"]

        logger.debug("Connecting to the keycloak server %s ...", server_url)

        try:
            keycloak_connection = KeycloakOpenIDConnection(
                server_url=server_url,
                realm_name=realm_name,
                client_id=client_id,
                client_secret_key=client_secret_key,
                verify=True,
            )
            logger.debug("Connected to the Keycloak server")
            return KeycloakAdmin(connection=keycloak_connection)

        except KeycloakError as error:
            raise RuntimeError(
                f"Error connecting with keycloak to '{server_url}', "
                f"realm_name={realm_name} with client_id={client_id}.",
            ) from error

    def get_keycloak_user_roles(self, keycloak_user: dict):
        return self.keycloak_admin.get_realm_roles_of_user(keycloak_user["id"])

    def get_keycloak_users(self) -> list[dict]:
        return self.keycloak_admin.get_users({})

    def get_obs_user_from_keycloak_user(self, keycloak_user: dict) -> str | None:
        try:
            return keycloak_user["attributes"]["obs-user"]  # TODO est-ce la bonne manière de récupérer les attributes ?
        except KeyError:
            return None

    def set_obs_user_in_keycloak_user(self, keycloak_user: dict, obs_user: str) -> dict[Any, Any]:
        keycloak_user["attributes"]["obs-user"] = obs_user
        return keycloak_user

    def update_keycloak_user(self, user_id: str, payload: dict):
        self.keycloak_admin.update_user(user_id=user_id, payload=payload)
