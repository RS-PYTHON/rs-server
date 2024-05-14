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

"""Contains all functions needed to manage the response endpoints."""

from rs_server_catalog.authentication_catalog import get_authorisation


def manage_catalog_collections_owner_id_endoint(
    collections: dict,
    auth_roles: list,
    owner_id: str,
    user_login: str,
) -> list:
    """Filter the collections allowed for the user calling this endpoint.

    Args:
        collections (dict): The list of all collections.
        auth_roles (list): The list of all authorisations for the user calling this endpoint.
        owner_id (str): The owner id.
        user_login (str):


    Returns:
        list: The filtered list containing accessible collections for the user.
    """
    return [
        collection
        for collection in collections
        if get_authorisation(collection["id"], auth_roles, "read", owner_id, user_login)
    ]
