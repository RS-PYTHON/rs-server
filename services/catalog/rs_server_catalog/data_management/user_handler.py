# Copyright 2023-2026 Airbus, CS Group
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
"""This library contains all functions needed for the fastAPI middleware."""

import getpass
import os
import re
from typing import Any
from urllib.parse import urlparse

from rs_server_catalog.utils import CATALOG_PREFIX
from rs_server_common.authentication import oauth2
from rs_server_common.utils.logging import Logging
from starlette.requests import Request

CATALOG_COLLECTIONS = CATALOG_PREFIX + "/collections"
CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX = (
    CATALOG_COLLECTIONS + r"(((?P<owner_collection_id>/.+?(?=/|$)))?"
    r"(?P<items>/.+?(?=/|$))?"
    r"(?P<item_id>/.+?(?=/|$))?)?"
)

# Regexp for catalog endpoints
COLLECTIONS_QUERYABLES_REGEX = CATALOG_COLLECTIONS + r"/((?P<owner_id>.+):)?(?P<collection_id>.+)/queryables"
BULK_ITEMS_REGEX = CATALOG_COLLECTIONS + r"/((?P<owner_id>.+):)?(?P<collection_id>.+)/bulk_items"

# Regexp for search endpoints
CATALOG_SEARCH = CATALOG_PREFIX + "/search"

logger = Logging.default(__name__)


def get_user(endpoint_user: str | None, apikey_user: str | None):
    """Retrieve the user identifier based on provided parameters. Default is the
    current running user (used for local mode in general)

    Args:
        endpoint_user (str): User identifier from the endpoint.
        apikey_user (str): User identifier from the API key.

    Returns:
        str: The user identifier.
    """
    if endpoint_user:
        return endpoint_user
    if apikey_user:
        return apikey_user
    return os.getenv("RSPY_HOST_USER", default=getpass.getuser())


def owner_id_and_collection_id(owner_id: str, collection_id: str) -> str:
    """Returns collection_id with owner_id prefix"""
    return collection_id if collection_id.startswith(f"{owner_id}_") else f"{owner_id}_{collection_id}"


def collection_id_without_owner_id(collection_id: str, owner_id: str) -> str:
    """Returns collection_id without owner_id prefix"""
    return collection_id.removeprefix(f"{owner_id}_")


def reroute_url(  # type: ignore # pylint: disable=too-many-branches,too-many-statements
    request: Request,
    ids_dict: dict[str, Any],
):
    """Get the RS Server backend catalog endpoints.

    Args:
        request (Request): The client request
        ids_dict (str): Dictionary to easily access important data of our request

    Raises:
        ValueError: If the path is not valid.
    """
    path = request.scope["path"]
    method = request.method
    patterns = [r"/favicon.ico"]

    # Catch one endpoint of the following list
    regexp_list = [
        "/",
        CATALOG_PREFIX,
        CATALOG_PREFIX + "/",
        CATALOG_SEARCH,
        CATALOG_PREFIX + "/queryables",
        CATALOG_PREFIX + "/api",
        CATALOG_PREFIX + "/api.html",
        CATALOG_PREFIX + "/docs/oauth2-redirect",
        CATALOG_PREFIX + "/conformance",
    ]
    if any(re.fullmatch(pattern, path) for pattern in regexp_list):
        # Don't validate other conditions if we alredy matched the previous regexps
        pass

    # Catch authentication endpoints (path should be left as it is in this case)
    elif path.startswith(f"{oauth2.AUTH_PREFIX}/"):
        pass

    # The endpoint PUT "/catalog/collections" does not exists.
    elif path.rstrip("/") == CATALOG_COLLECTIONS and method != "PUT":
        path = CATALOG_COLLECTIONS

    # Catch endpoint /catalog/collections/[{owner_id}:]{collection_id}/bulk_items
    elif match := re.fullmatch(BULK_ITEMS_REGEX, path):
        groups = match.groupdict()
        ids_dict["owner_id"] = get_user(groups["owner_id"], ids_dict["user_login"])
        ids_dict["collection_ids"].append(collection_id_without_owner_id(groups["collection_id"], ids_dict["owner_id"]))
        path = (
            CATALOG_COLLECTIONS
            + f"/{owner_id_and_collection_id(ids_dict['owner_id'], ids_dict['collection_ids'][0])}/bulk_items"
        )

    # Catch endpoint /catalog/collections/[{owner_id}:]{collection_id}/queryables
    elif match := re.fullmatch(COLLECTIONS_QUERYABLES_REGEX, path):
        groups = match.groupdict()
        ids_dict["owner_id"] = get_user(groups["owner_id"], ids_dict["user_login"])
        ids_dict["collection_ids"].append(collection_id_without_owner_id(groups["collection_id"], ids_dict["owner_id"]))
        path = (
            CATALOG_COLLECTIONS
            + f"/{owner_id_and_collection_id(ids_dict['owner_id'], ids_dict['collection_ids'][0])}/queryables"
        )

    # Catch all other endpoints.
    elif match := re.match(CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX, path):
        groups = match.groupdict()
        if groups["owner_collection_id"]:
            # protection for more than one : (example-> /catalog/collections/ownerId:collection:Id/items)
            # the list owner_collection_id_split has one or at most two members (note the maxsplit = 1)
            owner_collection_id_split = groups["owner_collection_id"].lstrip("/").split(":", 1)
            if len(owner_collection_id_split) == 1:
                # the following handles the absence of the ownerId param, for endpoints like:
                # /catalog/collections/collectionId/items
                ids_dict["owner_id"] = get_user(None, ids_dict["user_login"])
                ids_dict["collection_ids"].append(
                    collection_id_without_owner_id(owner_collection_id_split[0], ids_dict["owner_id"]),
                )
            else:
                # the following handles the presence of the ownerId param, for endpoints like:
                # /catalog/collections/ownerId:collectionId/items
                ids_dict["owner_id"] = owner_collection_id_split[0]
                ids_dict["collection_ids"].append(
                    collection_id_without_owner_id(owner_collection_id_split[1], ids_dict["owner_id"]),
                )

        # /catalog/collections/{owner_id}:{collection_id}
        # case is the same for PUT / POST / DELETE, but needs different paths
        collection_id = owner_id_and_collection_id(ids_dict["owner_id"], ids_dict["collection_ids"][0])
        if groups["items"] is None and method != "DELETE":
            path = CATALOG_COLLECTIONS + f"/{collection_id}"
        else:
            ids_dict["item_id"] = groups["item_id"]
            if ids_dict["item_id"] is None:
                if "/items" in path:
                    path = CATALOG_COLLECTIONS + f"/{collection_id}/items"
                else:
                    path = CATALOG_COLLECTIONS + f"/{collection_id}"
            else:
                ids_dict["item_id"] = ids_dict["item_id"][1:]
                path = CATALOG_COLLECTIONS + f"/{collection_id}/items/{ids_dict['item_id']}"

    elif not any(re.fullmatch(pattern, path) for pattern in patterns):
        path = ""
    # Finally, update the path of the request with the new route
    if path != request.scope["path"]:
        logger.debug(f"Rerouting {request.scope['path']} => {path}")
        request.scope["path"] = path


def add_user_prefix(
    path: str,
    user: str | None,
    collection_id: str | None,
    feature_id: str = "",
) -> str:
    """
    Modify the RS server backend catalog endpoint to get the RS server frontend endpoint

    Args:
        path (str): RS server backend endpoint.
        user (str): The user ID.
        collection_id (str): The collection id.
        feature_id (str): The feature id.

    Returns:
        str: The RS server frontend endpoint.
    """
    new_path = path

    if path == "/collections":
        new_path = CATALOG_COLLECTIONS

    elif path == "/search":
        new_path = CATALOG_SEARCH

    elif user and (path == "/"):
        new_path = CATALOG_PREFIX + "/"

    elif user and collection_id and (path == CATALOG_COLLECTIONS + f"/{user}_{collection_id}"):
        new_path = CATALOG_COLLECTIONS + f"/{user}:{collection_id}"

    elif user and collection_id and (path == CATALOG_COLLECTIONS + f"/{user}_{collection_id}/items"):
        new_path = CATALOG_COLLECTIONS + f"/{user}:{collection_id}/items"

    elif user and collection_id and (path == CATALOG_COLLECTIONS + f"/{user}_{collection_id}/queryables"):
        new_path = CATALOG_COLLECTIONS + f"/{user}:{collection_id}/queryables"

    elif (
        user
        and collection_id
        and (f"/collections/{user}_{collection_id}/items" in path or f"/collections/{collection_id}/items" in path)
    ):  # /catalog/.../items/item_id
        new_path = CATALOG_COLLECTIONS + f"/{user}:{collection_id}/items/{feature_id}"

    return new_path


def _owner_and_short_collection_id(collection_id: str, owner: str) -> tuple[str, str]:
    """Split a pgstac collection id "<owner>_<short_id>" without modifying any STAC object.

    The result is only meant to build links: the id of the STAC object itself keeps its owner prefix.

    Args:
        collection_id (str): The collection id as stored in pgstac (normally prefixed by its owner).
        owner (str): The owner that is expected as prefix.

    Returns:
        tuple[str, str]: The owner and the collection id without the owner prefix. If the id doesn't
            start with "<owner>_", the owner is empty and the id is returned as is.
    """
    if collection_id.startswith(f"{owner}_"):
        return owner, collection_id.removeprefix(f"{owner}_")
    return "", collection_id


def adapt_object_links(object_content: dict, current_user: str = "") -> dict:
    """Adapt all the links from a collection using the user and collection name they already contain,
    so the user can access them correctly

    Args:
        object_content (dict): The STAC object (item or collection) whose links need to be adapted.
        current_user (str): The currently connected user identifier (used as fallback owner).
    Returns:
        dict: The collection passed in parameter with adapted links
    """
    user = collection_id = feature_id = ""

    # The collection ids returned to the user keep their "<owner_id>_" prefix, so that they are unique
    # (STAC requires collection ids to be unique in the catalog) and identical to the ones stored in pgstac.
    # The prefix is only removed from the local `collection_id` variable, which is used to build the links:
    # the hrefs must contain "<owner_id>:<collection_id>" and never the prefixed id.
    # The objects are therefore never modified here, except for their links.

    # Case when object is an item
    if "properties" in object_content and "collection" in object_content:
        user, collection_id = _owner_and_short_collection_id(
            object_content["collection"],
            object_content["properties"].get("owner", current_user),
        )
        feature_id = object_content["id"]

    # Case when object is a collection
    elif "id" in object_content:
        user, collection_id = _owner_and_short_collection_id(
            object_content["id"],
            object_content.get("owner", current_user),
        )

    # Update links with user, collection and feature values retrieved from previous steps
    links = object_content.get("links", [])
    for j, link in enumerate(links):
        link_parser = urlparse(link["href"])
        new_path = add_user_prefix(link_parser.path, user, collection_id, feature_id)
        links[j]["href"] = link_parser._replace(path=new_path).geturl()

    return object_content


def adapt_links(content: dict, object_name: str, current_user: str = "", current_collection_id: str = "") -> dict:
    """Adapt all the links that are outside from the collection section with the given user and collection name,
    then the ones inside with the user and collection names they already contain.

    Args:
        content (dict): The response content from the middleware
        'call_next' loaded in json format.
        object_name (str): Type of object we want to also update.
        current_user (str): The user id that is currently connected.
        current_collection_id (str): The collection ID used to rewrite links outside the object list.

    Returns:
        dict: The content passed in parameter with adapted links
    """
    # Adapt links outside of objects with current user/collection situation
    links = content["links"]
    for link in links:
        link_parser = urlparse(link["href"])
        new_path = add_user_prefix(link_parser.path, current_user, current_collection_id)
        link["href"] = link_parser._replace(path=new_path).geturl()

    # Go through each object and apply corrections to the links using the object's info
    for i in range(len(content[object_name])):
        content[object_name][i] = adapt_object_links(content[object_name][i], current_user)

    return content
