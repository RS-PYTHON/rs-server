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
# pylint: disable=too-many-return-statements
"""This library contains all functions needed for the fastAPI middleware."""

import re
from typing import Tuple

CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX = (
    r"/catalog/collections"
    r"((?P<owner_collection_id>/.+?(?=/|$))"
    r"(?P<items>/.+?(?=/|$))?"
    r"(?P<item_id>/.+?(?=/|$))?)?"
)

CATALOG_OWNER_ID_REGEX = r"/catalog/catalogs/(?P<owner_id>.+)"
CATALOG_COLLECTION = "/catalog/collections"
CATALOG_SEARCH = "/catalog/search"


def reroute_url(path: str, method: str) -> Tuple[str, dict]:  # pylint: disable=too-many-branches
    """Remove the prefix from the RS Server Frontend endpoints to get the
    RS Server backend catalog endpoints.

    Args:
        path (str): RS Server Frontend endpoints.
        method (str): RS Server Fronted request method type.

    Raises:
        ValueError: If the path is not valid.

    Returns:
        str: Return the URL path with prefix removed.
        dict: Return a dictionary containing owner, collection and item ID.
    """

    patterns = [r"/_mgmt/ping", r"/conformance", r"/api.*", r"/docs/oauth2-redirect", r"/favicon.ico"]

    # if path == "/":
    #     raise ValueError(f"URL ({path}) is invalid.")

    ids_dict = {"owner_id": "", "collection_id": "", "item_id": ""}

    if "/health" in path:
        return "/health", ids_dict

    if path in ["/catalog/", "/"]:
        return "/", ids_dict

    if path == "/catalog/search":
        return "/search", ids_dict

    if path == CATALOG_COLLECTION and method != "PUT":  # The endpoint PUT "/catalog/collections" does not exists.
        return "/collections", ids_dict

    if path == "/catalog/queryables":
        return "/queryables", ids_dict

    # Moved to /catalogs/ (still interesting to keep this endpoint) - disabled for now
    # To catch the endpoint /catalog/catalogs/{owner_id}
    if match := re.fullmatch(CATALOG_OWNER_ID_REGEX, path):
        groups = match.groupdict()
        ids_dict["owner_id"] = groups["owner_id"]
        return "/", ids_dict

    # To catch all the other endpoints.
    if match := re.match(CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX, path):
        groups = match.groupdict()
        if groups["owner_collection_id"] and ":" in groups["owner_collection_id"]:
            ids_dict["owner_id"], ids_dict["collection_id"] = map(
                lambda x: x.lstrip("/"),
                groups["owner_collection_id"].split(":"),
            )
        # /catalog/collections/owner:collection case is the same for PUT / POST / DELETE, but needs different paths
        if groups["item_id"] is None and method == "PUT":
            path = "/collections"
        elif groups["items"] is None and method != "DELETE":
            path = f"/collections/{ids_dict['owner_id']}_{ids_dict['collection_id']}"
        else:
            ids_dict["item_id"] = groups["item_id"]
            if ids_dict["item_id"] is None:
                if "items" in path:
                    path = f"/collections/{ids_dict['owner_id']}_{ids_dict['collection_id']}/items"
                else:
                    path = f"/collections/{ids_dict['owner_id']}_{ids_dict['collection_id']}"
            else:
                ids_dict["item_id"] = ids_dict["item_id"][1:]
                path = f"/collections/{ids_dict['owner_id']}_{ids_dict['collection_id']}/items/{ids_dict['item_id']}"

    elif path == CATALOG_COLLECTION:
        path = "/collections"

    elif "catalog" not in path and not any(re.match(pattern, path) for pattern in patterns):
        raise ValueError(f"Path {path} is invalid.")
    return path, ids_dict


def add_user_prefix(  # pylint: disable=too-many-return-statements
    path: str,
    user: str,
    collection_id: str,
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
    if path == "/collections":
        return CATALOG_COLLECTION

    if path == "/search":
        return CATALOG_SEARCH

    if user and (path == "/"):
        return f"/catalog/catalogs/{user}"

    if user and collection_id and (path == f"/collections/{user}_{collection_id}"):
        return f"/catalog/collections/{user}:{collection_id}"

    if user and collection_id and (path == f"/collections/{user}_{collection_id}/items"):
        return f"/catalog/collections/{user}:{collection_id}/items"

    if (
        user
        and collection_id
        and (f"/collections/{user}_{collection_id}/items" in path or f"/collections/{collection_id}/items" in path)
    ):  # /catalog/.../items/item_id
        return f"/catalog/collections/{user}:{collection_id}/items/{feature_id}"

    return path


def remove_user_from_feature(feature: dict, user: str) -> dict:
    """Remove the user ID from the collection name in the feature.

    Args:
        feature (dict): a geojson that contains georeferenced
        data and metadata like the collection name.
        user (str): The user ID.

    Returns:
        dict: the feature with a new collection name without the user ID.
    """
    if user in feature["collection"]:
        feature["collection"] = feature["collection"].removeprefix(f"{user}_")
    return feature


def remove_user_from_collection(collection: dict, user: str) -> dict:
    """Remove the user ID from the id section in the collection.

    Args:
        collection (dict): A dictionary that contains metadata
        about the collection content like the id of the collection.
        user (str): The user ID.

    Returns:
        dict: The collection without the user ID in the id section.
    """
    if user in collection["id"]:
        collection["id"] = collection["id"].removeprefix(f"{user}_")
    return collection


def filter_collections(collections: list[dict], user: str) -> list[dict]:
    """filter the collections according to the user ID.

    Args:
        collections (list[dict]): The list of collections available.
        user (str): The user ID.

    Returns:
        list[dict]: The list of collections corresponding to the user ID
    """
    return [collection for collection in collections if user in collection["id"]]
