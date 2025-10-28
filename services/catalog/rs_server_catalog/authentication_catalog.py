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
    auth_role_pattern = (
        r"rs_catalog_(?P<owner_id>.*(?=:)):"  # Group owner_id
        r"(?P<collection_id>.+)_"  # Group collection_id
        r"(?P<type_of_right>read|write|download)"  # Group type_of_right
        r"(?=$)"  # Lookahead for end of line
    )
    if user_login == requested_owner_id:
        return True

    # Check for each requested collection that we have are allowed to access according to the requested type of right
    parsed_auth_roles = []
    for role in auth_roles:
        if match := re.match(auth_role_pattern, role):
            parsed_auth_roles.append(match.groupdict())
    for requested_col_id in requested_col_ids:
        for auth_role in parsed_auth_roles:
            if owner_prefix:
                requested_col_id = requested_col_id.removeprefix(f"{auth_role['owner_id']}_")
            if (auth_role["collection_id"] != "*") and (requested_col_id != auth_role["collection_id"]):
                return False  # not authorized
            if requested_owner_id != auth_role["owner_id"]:
                return False
            if type_of_right != auth_role["type_of_right"]:
                return False

    # We are authorized only if the user has all roles for all collections
    return True
