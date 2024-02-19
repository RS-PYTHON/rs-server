"""This library contains all functions needed for the fastAPI middleware."""

import re

CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX = r"""/catalog(?P<owner_id>.*)(?P<collections>/collections)
    ((?P<collection_id>/.+?(?=/|$))(?P<items>.*)?)?"""


def remove_user_prefix(path: str) -> str:
    """Remove the prefix from the RS Server Frontend endpoints to get the
    RS Server backend catalog endpoints.

    Args:
        path (str): RS Server Frontend endpoints.

    Raises:
        ValueError: If the path is not valid.

    Returns:
        str: Return the URL path with prefix removed.
    """

    if path == "/":
        raise ValueError("URL (/) is invalid.")

    if path == "/catalog":
        raise ValueError("URL (/catalog) is invalid.")

    res = path
    match = re.search(CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX, path)
    if match:
        groups = match.groupdict()
        owner_id = groups["owner_id"][1:]
        collection_id = groups["collection_id"]
        items = groups["items"]
        if collection_id is None:
            return "/collections", owner_id
        collection_id = groups["collection_id"][1:]
        if items == "":
            return f"/collections/{owner_id}_{collection_id}", owner_id
        return f"/collections/{owner_id}_{collection_id}/items", owner_id

    return res, ""


def add_user_prefix(path: str, user: str, collection_id: str) -> str:
    """Modify the RS server backend catalog endpoint to get the RS server frontend endpoint.

    Args:
        path (str): RS server backend endpoint.
        user (str): The user ID.

    Returns:
        str: The RS server frontend endpoint.
    """
    if path == "/":
        return f"/catalog/{user}"
    if path == "/collections":
        return f"/catalog/{user}/collections"
    if path == f"/collections/{user}_{collection_id}":
        return f"/catalog/{user}/collections/{collection_id}"
    if path == f"/collections/{user}_{collection_id}/items":
        return f"/catalog/{user}/collections/{collection_id}/items"
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
