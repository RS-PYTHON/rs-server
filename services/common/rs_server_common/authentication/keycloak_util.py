# Copyright 2024 CS Group
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

"""Utility module to get user information from the KeyCloak server."""


import os
from dataclasses import dataclass

from keycloak import KeycloakAdmin, KeycloakError, KeycloakOpenIDConnection
from keycloak.exceptions import KeycloakGetError
from rs_server_common.utils.logging import Logging
from starlette.status import HTTP_404_NOT_FOUND

logger = Logging.default(__name__)


@dataclass
class KCInfo:
    """
    User information from KeyCloak.

    Attributes:
        is_enabled (bool): is the user enabled in KeyCloak ?
        roles (list[str]): IAM roles given to the user in KeyCloak.
    """

    is_enabled: bool
    roles: list[str]


class KCUtil:  # pylint: disable=too-few-public-methods
    """Utility class to get user information from the KeyCloak server."""

    def __init__(self) -> None:
        """Constructor."""
        self.keycloak_admin = self.__get_keycloak_admin()

    def __get_keycloak_admin(self) -> KeycloakAdmin:
        """Init and return an admin KeyCloak connection."""

        oidc_endpoint = os.environ["OIDC_ENDPOINT"]
        oidc_realm = os.environ["OIDC_REALM"]
        oidc_client_id = os.environ["OIDC_CLIENT_ID"]
        oidc_client_secret = os.environ["OIDC_CLIENT_SECRET"]

        logger.debug(f"Connecting to the keycloak server {oidc_endpoint} ...")
        try:
            keycloak_connection = KeycloakOpenIDConnection(
                server_url=oidc_endpoint,
                realm_name=oidc_realm,
                client_id=oidc_client_id,
                client_secret_key=oidc_client_secret,
                verify=True,
            )
            logger.debug("Connected to the keycloak server")
            return KeycloakAdmin(connection=keycloak_connection)

        except KeycloakError as error:
            raise RuntimeError(
                f"Error connecting with keycloak to '{oidc_endpoint}', "
                f"realm_name={oidc_realm} with client_id="
                f"{oidc_client_id}.",
            ) from error

    def get_user_info(self, user_id: str) -> KCInfo:
        """Get user information from the KeyCloak server."""

        try:
            kadm = self.keycloak_admin
            user = kadm.get_user(user_id)
            iam_roles = [role["name"] for role in kadm.get_composite_realm_roles_of_user(user_id)]
            return KCInfo(user["enabled"], iam_roles)

        except KeycloakGetError as error:

            # If the user is not found, this means he was removed from keycloak.
            # Thus we must remove all his api keys from the database.
            if (error.response_code == HTTP_404_NOT_FOUND) and (
                "User not found" in error.response_body.decode("utf-8")
            ):
                logger.warning(f"User '{user_id}' not found in keycloak.")
                return KCInfo(False, [])

            # Raise other exceptions
            raise
