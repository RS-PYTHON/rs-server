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

from starlette.responses import JSONResponse


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


def manage_landing_page(
    auth_roles: list,
    user_login: str,
    content: dict,
) -> dict | JSONResponse:
    """Remove unauthorized collections links.

    Args:
        auth_roles (list): list of roles of the api-key.
        user_login (str): The api-key owner.
        content (dict): The landing page.

    Returns:
        dict: The updated landingpage.
    """
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
