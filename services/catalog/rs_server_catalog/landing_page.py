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

"""Contains all functions for the landing page."""

import re

from starlette.requests import Request


def add_catalogs(request: Request, auth_roles: list, user_login: str, content: dict) -> dict:
    """This function returns a list of links with all catalogs that the user has access to.
    We use the list auth_roles to access to all authorizations for the user.
    Args:
        request (Request): The client request.
        auth_roles (list): list of roles of the api-key.
        user_login (str): The api-key owner.
        content (dict): The landing page.

    Returns:
        dict: The updated content with all catalogs that the user has access to.
    """
    catalog_read_right_pattern = (
        r"rs_catalog_(?P<owner_id>.*(?=:)):(?P<collection_id>.+)_(?P<right_type>read|write|download)(?=$)"
    )
    # Add catalogs links that the user can access to.
    for role in auth_roles:
        if match := re.match(catalog_read_right_pattern, role):
            groups = match.groupdict()
            if user_login != groups["owner_id"] and groups["collection_id"] == "*" and groups["right_type"] == "read":
                child_link = {
                    "rel": "child",
                    "type": "application/json",
                    "href": "",
                }
                url = request.url
                child_link["href"] = f"{url}{groups['owner_id']}"
                content["links"].append(child_link)
                # content["links"] = [
                #     link for link in content["links"] if f"{groups['owner_id']}_" not in link["href"]
                # ]  # to remove all the collection links and keep only catalogs.
    return content


def get_unauthorized_collections_links(auth_roles: list, content: dict) -> list:
    """This function uses the authorisation roles list to get all unauthorized collections.

    Args:
        auth_roles (list): list of roles of the api-key.
        content (dict): The landing page.

    Returns:
        list: The list of all unauthorized collections.
    """
    catalog_read_right_pattern = (
        r"rs_catalog_(?P<owner_id>.*(?=:)):(?P<collection_id>.+)_(?P<right_type>read|write|download)(?=$)"
    )
    # Delete all collections that the user does not have access to.
    unauthorized_collections = []
    for link in content["links"]:  # Only check child links.
        authorized = 0
        if link["rel"] == "child":
            for role in auth_roles:  # Check in the authorisations list if the link is allowed to the user.
                if match := re.match(catalog_read_right_pattern, role):
                    groups = match.groupdict()
                    if (
                        groups["owner_id"] in link["href"]
                        and (groups["collection_id"] == "*" or groups["collection_id"] in link["href"])
                        and groups["right_type"] == "read"
                    ):
                        authorized = 1
                        break
            if not authorized:
                unauthorized_collections.append(link)
    return unauthorized_collections


def manage_landing_page(request: Request, auth_roles: list, user_login: str, content: dict) -> dict:
    """All sub user catalogs accessible by the user calling it are returned as "child" links.

    Args:
        request (Request): The client request.
        auth_roles (list): list of roles of the api-key.
        user_login (str): The api-key owner.
        content (dict): The landing page.

    Returns:
        dict: The updated landingpage.
    """
    content = add_catalogs(request, auth_roles, user_login, content)
    unauthorized_collections = get_unauthorized_collections_links(auth_roles, content)
    content["links"] = [link for link in content["links"] if link not in unauthorized_collections]
    return content
