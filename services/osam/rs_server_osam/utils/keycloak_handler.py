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
        Retrieves the 'obs-user' attribute for a given Keycloak username.

        This function attempts to find the user's ID, fetch their full details,
        and then extract the 'obs-user' attribute from their 'attributes' dictionary.

        Args:
            username (str): The username of the Keycloak user to retrieve.

        Returns:
            str or None: The value of the 'obs-user' attribute if found and valid;
                         otherwise, None if the user or attribute isn't found,
                         or an error occurs during retrieval.

        Raises:
            KeycloakConnectionError: Re-raised if there's a critical issue connecting
                                     to the Keycloak server. This indicates a network
                                     or server availability problem.
            KeycloakAuthenticationError: Re-raised if the KeycloakAdmin instance lacks
                                         proper authentication or sufficient permissions
                                         to perform the operation. This is a critical
                                         configuration error.
        """
        obs_user_value: str | None = None  # Initialize the variable to hold the result

        try:
            # Step 1: Get Keycloak user ID
            # get_user_id typically raises KeycloakError if the user is not found.
            keycloak_user_id = self.keycloak_admin.get_user_id(username)

            # Step 2: Get Keycloak user details using the ID
            keycloak_user = self.keycloak_admin.get_user(keycloak_user_id)  # type: ignore

            # Step 3: Safely extract 'obs-user' attribute
            if keycloak_user and "attributes" in keycloak_user:
                obs_user_raw = keycloak_user["attributes"].get("obs-user")

                if obs_user_raw is None:
                    print(
                        f"Warning: 'obs-user' attribute not found for user '{username}' \
                          (ID: {keycloak_user_id}).",
                    )
                elif isinstance(obs_user_raw, list) and len(obs_user_raw) > 0:
                    obs_user_value = obs_user_raw[0]
                elif isinstance(obs_user_raw, str):
                    obs_user_value = obs_user_raw
                else:
                    print(
                        f"Warning: 'obs-user' attribute for user '{username}' (ID: {keycloak_user_id}) has \
                            an unexpected type: {type(obs_user_raw)}. Value: {obs_user_raw}",
                    )
            else:
                # This could happen if get_user returns an unexpected structure,
                # or if the 'attributes' key is entirely missing.
                print(
                    f"Warning: Keycloak user details or 'attributes' key missing for \
                        '{username}' (ID: {keycloak_user_id}).",
                )

        except (KeycloakConnectionError, KeycloakAuthenticationError) as e:
            # These are fundamental errors indicating a problem with Keycloak
            # connectivity or the admin credentials. Re-raise them.
            print(f"CRITICAL Keycloak error for username '{username}': {e}")
            raise
        except KeycloakError as e:
            # This catches Keycloak-specific errors like "user not found" from
            # get_user_id or other issues during user data retrieval.
            print(f"Keycloak error during user retrieval for '{username}': {e}")
            # obs_user_value remains None by default
        except Exception as e:  # pylint: disable = broad-exception-caught
            # Catch any other unexpected Python errors.
            print(f"An unexpected error occurred while processing user '{username}': {e}")
            # obs_user_value remains None by default

        return obs_user_value

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
