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

"""Contains all functions used to manage the authentication in the catalog."""

import re


def get_authorisation(
    requested_col_ids: list[str],
    auth_roles: list[str],
    type_of_right: str,
    requested_owner_id: str,
    user_login: str,
    owner_prefix: bool = False,
) -> bool:
    """
    Check if the user is authorized to access collections.

    Args:
        requested_col_ids (list): IDs of the requested collections.
        auth_roles (list): The list of authorisation for the user_login.
        type_of_right (str): the type of the right. Can be read, write or download.
        requested_owner_id (str): The name of the owner of the collection {collection_id}.
        user_login (str): The owner of the key linked to the request.
        owner_prefix (bool): True if the collection IDs are prefixed by their collection <owner>_

    Returns:
        bool: True if the user is authorized, else False
    """
    # The UAC/Keycloak user (who is also the owner of the api key and oauth2 cookie)
    # always has all the rights on all the collections he owns.
    if user_login == requested_owner_id:
        return True

    # Parse authorization roles to retrieve the role owner_id, collection_id and type of right
    auth_role_pattern = (
        r"rs_catalog_(?P<owner_id>.*(?=:)):"  # Group owner_id
        r"(?P<collection_id>.+)_"  # Group collection_id
        r"(?P<type_of_right>read|write|download)"  # Group type_of_right
        r"(?=$)"  # Lookahead for end of line
    )
    parsed_auth_roles = []
    for role in auth_roles:
        if match := re.match(auth_role_pattern, role):
            parsed_auth_roles.append(match.groupdict())

    # For each requested collection
    for requested_col_id in requested_col_ids:

        # Does the user have at least one role that authorizes him to request this collection ?
        requested_col_ok = False
        for auth_role in parsed_auth_roles:

            if owner_prefix:
                requested_col_id = requested_col_id.removeprefix(f"{auth_role['owner_id']}_")

            col_id_ok = (auth_role["collection_id"] == "*") or (requested_col_id == auth_role["collection_id"])
            owner_ok = requested_owner_id == auth_role["owner_id"]
            type_ok = type_of_right == auth_role["type_of_right"]

            if col_id_ok and owner_ok and type_ok:
                requested_col_ok = True

        # Return False if the user is not authorized for at least one collection
        if not requested_col_ok:
            return False

    # Return True if the user is authorized for all collections
    return True
