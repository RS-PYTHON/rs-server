# Copyright 2023-2025 Airbus, CS Group
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

"""Contains all functions used to manage the authentication in the catalog."""

import re

from fastapi import HTTPException
from rs_server_catalog.data_management.user_handler import get_user
from rs_server_common import settings
from rs_server_common.utils.logging import Logging
from starlette.status import HTTP_401_UNAUTHORIZED

logger = Logging.default(__name__)


def get_authorisation(
    requested_col_ids: list[str],
    auth_roles: list[str],
    requested_action: str,
    requested_owner_id: str,
    user_login: str,
    owner_prefix: bool = False,
    raise_if_unauthorized: bool = False,
) -> bool:
    """
    Check if the user is authorized to access collections.

    Args:
        requested_col_ids (list): IDs of the requested collections.
        auth_roles (list): The list of authorisations for the user_login.
        requested_action (str): Requested action (read, write or download) on the collections.
        requested_owner_id (str): The name of the owner of the collection {collection_id}.
        user_login (str): The owner of the apikey or oauth2 cookie linked to the request.
        owner_prefix (bool): True if the collection IDs are prefixed by their collection <owner>_
        raise_if_unauthorized (bool): If True, raise an HTTPException if the user is unauthorized

    Returns:
        bool: True if the user is authorized, else False
    """
    # No authorization needed in local mode
    if settings.LOCAL_MODE:
        return True

    # The UAC/Keycloak user (who is also the owner of the api key and oauth2 cookie)
    # always has all the rights on all the collections he owns.
    if user_login == requested_owner_id:
        return True

    # Parse authorization roles to retrieve the role owner_id, collection_id and action.
    # Role format is: rs_catalog_<owner_id>:<collection_id>_<read|write|download>
    auth_role_pattern = (
        r"rs_catalog_(?P<owner_id>.*(?=:)):"  # Group owner_id
        r"(?P<collection_id>.+)_"  # Group collection_id
        r"(?P<action>read|write|download)"  # Group action
        r"(?=$)"  # Lookahead for end of line
    )
    parsed_auth_roles = []
    for role in auth_roles:
        if match := re.match(auth_role_pattern, role):
            parsed_auth_roles.append(match.groupdict())

    # For each requested collection
    for _requested_col_id in requested_col_ids:

        # Does the user have at least one role that authorizes him to request this collection ?
        requested_col_ok = False
        for auth_role in parsed_auth_roles:

            # Remove the owner prefix from the requested collection id, if any
            if owner_prefix:
                requested_col_id = _requested_col_id.removeprefix(f"{requested_owner_id}_")
            else:
                requested_col_id = _requested_col_id

            # Does this role give the authorization to this collection ID ?
            col_id_ok = (auth_role["collection_id"] == "*") or (auth_role["collection_id"] == requested_col_id)

            # Does this role give the authorization to this collection owner ?
            owner_ok = (auth_role["owner_id"] == "*") or (auth_role["owner_id"] == requested_owner_id)

            # Does this role give the authorization to this collection for read/write/download ?
            action_ok = auth_role["action"] == requested_action

            # All conditions must be met for this role to give the authorization to the collection
            if col_id_ok and owner_ok and action_ok:
                requested_col_ok = True
                break  # no need to check other roles

        # The user has no role that authorizes him to request this collection.
        # Return False if the user is not authorized for at least one collection.
        if not requested_col_ok:
            if raise_if_unauthorized:
                requested_roles = [
                    f"rs_catalog_{requested_owner_id}:{msg_col_id}_{requested_action}"
                    for msg_col_id in requested_col_ids
                ]
                raise HTTPException(
                    status_code=HTTP_401_UNAUTHORIZED,
                    detail=f"Missing authorization role(s): {requested_roles} "
                    + f"for user {user_login!r} with roles: {auth_roles}",
                )
            return False

    # Return True if the user is authorized for all collections
    return True


def check_user_authorization(request_ids: dict) -> None:
    """
    Checks that current user/owner is allowed to do operations on catalog objects.

    Raises:
        HTTPException: When the user doesn't have the expected authorizations
    """
    # Retrieve owner ID and check authorizations
    if not request_ids["owner_id"]:
        request_ids["owner_id"] = get_user(None, request_ids["user_login"])
    # If we are in cluster mode and the user_login is not authorized
    # to put/post/patch raise a HTTP_401_UNAUTHORIZED status.
    if settings.CLUSTER_MODE:
        get_authorisation(
            request_ids["collection_ids"],
            request_ids["auth_roles"],
            "write",
            request_ids["owner_id"],
            request_ids["user_login"],
            raise_if_unauthorized=True,
        )


def get_all_accessible_collections(collections: dict, auth_roles: list, user_login: str) -> list[dict]:
    """Return the list of all collections accessible by the user calling it.

    Args:
        collections (dict): List of all collections.
        auth_roles (list): List of roles of the api-key.
        user_login (str): The api-key owner.

    Returns:
        dict: The list of all collections accessible by the user.
    """
    # Test user authorization on each collection
    accessible_collections = [
        requested_col
        for requested_col in collections
        if get_authorisation(
            [requested_col["id"]],
            auth_roles,
            "read",
            requested_col["owner"],
            user_login,
            owner_prefix=True,
        )
    ]

    # Return results, sorted by <owner>_<collection_id>
    return sorted(accessible_collections, key=lambda col: col["id"])
