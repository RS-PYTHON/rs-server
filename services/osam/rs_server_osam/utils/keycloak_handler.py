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

"""Class to handle connection and requests to Keycloak"""

import logging
import os

from keycloak import KeycloakAdmin, KeycloakError, KeycloakOpenIDConnection

logger = logging.getLogger(__name__)


class KeycloakHandler:
    """Class to handle connection and requests to Keycloak"""

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

    def get_keycloak_user_roles(self, user_id: str) -> list[dict]:
        """Returns the list of roles for a given user
        RoleRepresentation: https://www.keycloak.org/docs-api/latest/rest-api/index.html#RoleRepresentation

        Args:
            user_id (str): ID of user for who we want the roles

        Returns:
            list[dict]: List of RoleRepresentation as dicts
        """
        return self.keycloak_admin.get_realm_roles_of_user(user_id)

    def get_keycloak_users(self) -> list[dict]:
        """Returns the list of all Keycloak users
        UserRepresentation: https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation

        Returns:
            list[dict]: List of UserRepresentation as dicts
        """
        return self.keycloak_admin.get_users({})

    def get_obs_user_from_keycloak_user(self, keycloak_user: dict) -> str | None:
        """Retrieves the attribute 'obs-user' from the given Keycloak user.
        Returns None if the field doesn't exist.

        Args:
            keycloak_user (dict): UserRepresentation (https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation)

        Returns:
            str | None: obs user ID or None
        """
        try:
            return keycloak_user["attributes"]["obs-user"]
        except KeyError:
            return None

    def set_obs_user_in_keycloak_user(self, keycloak_user: dict, obs_user: str) -> dict:
        """Sets the attribute 'obs-user' in the given Keycloak user.

        Args:
            keycloak_user (dict): UserRepresentation (https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation)

        Returns:
            dict: UserRepresentation (https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation)
        """
        if "attributes" not in keycloak_user.keys():
            keycloak_user["attributes"] = {}
        keycloak_user["attributes"]["obs-user"] = obs_user
        return keycloak_user

    def update_keycloak_user(self, user_id: str, payload: dict):
        """Updates the Keycloak user linked to the given user_id with the given payload.
        The payload must follow Keycloak's UserRepresentation:
        https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation

        Args:
            user_id (str): ID of the Keycloak user to update
            payload (dict): UserRepresentation with the up-to-date data
        """
        self.keycloak_admin.update_user(user_id=user_id, payload=payload)
