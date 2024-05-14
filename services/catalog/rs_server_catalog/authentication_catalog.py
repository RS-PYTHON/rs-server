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


def get_authorisation(collection_id: str, auth_roles: list, type_of_right: str, owner_id: str, user_login: str) -> bool:
    """_summary_

    Args:
        collection_id (str): The collection id.
        auth_roles (list): The list of authorisation for the user_login.
        type_of_right (str): the type of the right. Can be read, write or download.
        owner_id (str): The name of the owner of the collection {collection_id}.
        user_login: The owner of the key linked to the request.

    Returns:
        bool: _description_
    """
    catalog_read_right_pattern = (
        r"rs_catalog_(?P<owner_id>.*(?=:)):"  # Group owner_id
        r"(?P<collection_id>.+)_"  # Group collection_id
        r"(?P<type_of_right>read|write|download)"  # Group type_of_right
        r"(?=$)"  # Lookahead for end of line
    )
    if user_login == owner_id:
        return True
    for role in auth_roles:
        if match := re.match(catalog_read_right_pattern, role):
            groups = match.groupdict()
            if (
                (collection_id == groups["collection_id"] or groups["collection_id"] == "*")
                and owner_id == groups["owner_id"]
                and type_of_right == groups["type_of_right"]
            ):
                return True

    return False
