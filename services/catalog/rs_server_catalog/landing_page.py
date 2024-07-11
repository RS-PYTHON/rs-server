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
from starlette.responses import JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED


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

                urls = str(request.url).split("?")  # split by query params
                href = f"{urls[0]}catalogs/{groups['owner_id']}"

                # To be discussed: maybe we should add the query params (urls[1:])
                # but I guess we should not add e.g. the apikey because it's confidential.

                child_link = {
                    "rel": "child",
                    "type": "application/json",
                    "href": href,
                }
                content["links"].append(child_link)
                # content["links"] = [
                #     link for link in content["links"] if f"{groups['owner_id']}_" not in link["href"]
                # ]  # to remove all the collection links and keep only catalogs.
    return content


def get_unauthorized_collections_links(auth_roles: list, user_login: str, content: dict) -> list:
    """This function uses the authorisation roles list to get all unauthorized collections.

    Args:
        auth_roles (list): List of roles of the api-key.
        user_login (str): The api-key owner.
        content (dict): The landing page.

    Returns:
        list: The list of all unauthorized collections.
    """
    catalog_read_right_pattern = (
        r"rs_catalog_(?P<owner_id>.*(?=:)):(?P<collection_id>.+)_(?P<right_type>read|write|download)(?=$)"
    )
    collection_pattern = r"(?P<owner_id>.*?)_(?P<collection_id>.*)"
    # Delete all collections that the user does not have access to.
    unauthorized_collections = []
    for link in content["links"]:  # Only check child links.
        owner_id = ""
        if "title" in link and (match := re.match(collection_pattern, link["title"])):
            groups = match.groupdict()
            owner_id = groups["owner_id"]
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
            if not authorized and user_login != owner_id:
                unauthorized_collections.append(link)
    return unauthorized_collections


def keep_only_owner_id_auth_role(auth_roles, owner_id):
    """This function is called if the endpoint is /catalog/catalogs/owner_id.
    The function will only keep the authorizations of the owner_id if they exist
    all the others collections will be deleted.

    Args:
        auth_roles (list): list of roles of the api-key.
        owner_id (_type_): The owner id found in the path.

    Returns:
        _type_: The updated auth_roles.
    """
    new_auth_roles = []
    catalog_read_right_pattern = (
        r"rs_catalog_(?P<owner_id>.*(?=:)):(?P<collection_id>.+)_(?P<right_type>read|write|download)(?=$)"
    )
    for role in auth_roles:
        if match := re.match(catalog_read_right_pattern, role):
            groups = match.groupdict()
            if groups["owner_id"] == owner_id and groups["right_type"] == "read":
                new_auth_roles.append(role)
    return new_auth_roles


def manage_landing_page(
    request: Request,
    auth_roles: list,
    user_login: str,
    content: dict,
    owner_id: str,
) -> dict | JSONResponse:
    """All sub user catalogs accessible by the user calling it are returned as "child" links.

    Args:
        request (Request): The client request.
        auth_roles (list): list of roles of the api-key.
        user_login (str): The api-key owner.
        content (dict): The landing page.
        owner_id (str): The owner id found in the path.
        (to differentiate /catalog/ to /catalog/catalogs/owner_id)

    Returns:
        dict: The updated landingpage.
    """
    if not owner_id:
        content = add_catalogs(request, auth_roles, user_login, content)
    else:
        auth_roles = keep_only_owner_id_auth_role(auth_roles, owner_id)
        if not auth_roles and owner_id != user_login:
            detail = {"error": "Unauthorized access."}
            return JSONResponse(content=detail, status_code=HTTP_401_UNAUTHORIZED)
    unauthorized_collections = get_unauthorized_collections_links(auth_roles, user_login, content)

    content["links"] = [link for link in content["links"] if link not in unauthorized_collections]
    return content


def add_prefix_link_landing_page(content: dict, url: str):
    """add the prefix '/catalog' if it is not present

    Args:
        content (dict): the landing page
        url (str): the url
    """
    for link in content["links"]:
        if "href" in link and "/catalog" not in link["href"]:
            href = link["href"]
            url_size = len(url)
            link["href"] = href[:url_size] + "/catalog" + href[url_size:]
    return content
