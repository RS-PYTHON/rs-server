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
from keycloak.exceptions import (
    KeycloakAuthenticationError,
    KeycloakConnectionError,
    KeycloakPutError,
)

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
            keycloak_user (dict): UserRepresentation
            (https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation)

        Returns:
            str | None: obs user ID or None
        """
        try:
            return keycloak_user["attributes"]["obs-user"]
        except KeyError:
            return None

    def get_obs_user_from_keycloak_username(self, username: str) -> str | None:
        """
        Fetches the 'obs-user' attribute from Keycloak for the given username.

        Returns:
            str or None: The 'obs-user' value if available, otherwise None.

        Raises:
            KeycloakConnectionError, KeycloakAuthenticationError: For critical Keycloak issues.
        """
        try:
            user_id = self.keycloak_admin.get_user_id(username)
            user = self.keycloak_admin.get_user(user_id)  # type: ignore
            attributes = user.get("attributes", {}) if user else {}

            obs_user = attributes.get("obs-user")
            if isinstance(obs_user, list) and obs_user:
                return obs_user[0]
            if isinstance(obs_user, str):
                return obs_user

            logger.warning(
                f"Unexpected or missing 'obs-user' for '{username}' (ID: {user_id}). "
                f"Type: {type(obs_user)} Value: {obs_user}",
            )
        except (KeycloakConnectionError, KeycloakAuthenticationError) as e:
            logger.critical(f"Keycloak critical error for '{username}': {e}")
            raise
        except KeycloakError as e:
            logger.error(f"Keycloak error retrieving user '{username}': {e}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception(f"Unexpected error for user '{username}': {e}")

        return None

    def set_obs_user_in_keycloak_user(self, keycloak_user: dict, obs_user: str):
        """Sets the attribute 'obs-user' in the given Keycloak user.

        Args:
            keycloak_user (dict): UserRepresentation
            (https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation)

        Returns:
            dict: UserRepresentation (https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation)
        """
        attributes = keycloak_user.get("attributes", {})
        attributes["obs-user"] = [obs_user]  # Must be a list

        payload = {"attributes": attributes}

        self.keycloak_admin.update_user(user_id=keycloak_user["id"], payload=payload)

    def update_keycloak_user(self, user_id: str, payload: dict):
        """Updates the Keycloak user linked to the given user_id with the given payload.
        The payload must follow Keycloak's UserRepresentation:
        https://www.keycloak.org/docs-api/latest/rest-api/index.html#UserRepresentation

        Args:
            user_id (str): ID of the Keycloak user to update
            payload (dict): UserRepresentation with the up-to-date data
        """
        try:
            self.keycloak_admin.update_user(user_id=user_id, payload=payload)
        except KeycloakPutError as kpe:
            raise RuntimeError(f"Could not update client, {kpe}") from kpe
