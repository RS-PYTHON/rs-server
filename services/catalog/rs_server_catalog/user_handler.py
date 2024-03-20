"""This library contains all functions needed for the fastAPI middleware."""
import re

CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX = (
    r"/catalog/collections"
    r"((?P<owner_collection_id>/.+?(?=/|$))"
    r"(?P<items>/.+?(?=/|$))?"
    r"(?P<item_id>/.+?(?=/|$))?)?"
)

CATALOG_OWNER_ID_REGEX = r"/catalog/(?P<owner_id>[^\/]+)"


def get_ids(path: str) -> dict:
    """From a str path return the owner_id and the collection_id if they exists.


    Args:
        path (str): the endpoint request.

    Returns:
        dict: the result containing owner_id and collection_id.
    """
    res = {"owner_id": "", "collection_id": "", "item_id": ""}

    # To catch the endpoint /catalog/{owner_id}
    if match := re.fullmatch(CATALOG_OWNER_ID_REGEX, path):
        groups = match.groupdict()
        res["owner_id"] = groups["owner_id"]
        return res

    # To catch all the other endpoints.
    if match := re.match(CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX, path):
        groups = match.groupdict()
        if ":" in groups["owner_collection_id"]:
            res["owner_id"], res["collection_id"] = map(
                lambda x: x.lstrip("/"),
                groups["owner_collection_id"].split(":"),
            )
        if groups["item_id"]:
            res["item_id"] = groups["item_id"][1:]
        return res

    return res


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

    if path == "/catalog/search":
        return "/search"

    if path == "/catalog/collections":
        return "/collections"

    # Moved to /catalogs/ (still interesting to keep this endpoint) - disabled for now
    # # To catch the endpoint /catalog/{owner_id}
    # if match := re.fullmatch(CATALOG_OWNER_ID_REGEX, path):
    #     groups = match.groupdict()
    #     owner_id = groups["owner_id"]
    #     return "/"

    # To catch all the other endpoints.
    if match := re.match(CATALOG_OWNER_ID_STAC_ENDPOINT_REGEX, path):
        groups = match.groupdict()
        if ":" in groups["owner_collection_id"]:
            owner_id, collection_id = map(lambda x: x.lstrip("/"), groups["owner_collection_id"].split(":"))
        item_id = groups["item_id"]
        if item_id is None:
            if "items" in path:
                path = f"/collections/{owner_id}_{collection_id}/items"
            else:
                path = f"/collections/{owner_id}_{collection_id}"
        else:
            item_id = item_id[1:]
            path = f"/collections/{owner_id}_{collection_id}/items/{item_id}"

    return path


def add_user_prefix(path: str, user: str, collection_id: str, feature_id: str = "") -> str:
    """Modify the RS server backend catalog endpoint to get the RS server frontend endpoint.

    Args:
        path (str): RS server backend endpoint.
        user (str): The user ID.
        collection_id (str): The collection id.
        feature_id (str): The feature id.

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
    if f"/collections/{user}_{collection_id}/items" in path:  # /catalog/.../items/item_id
        return f"/catalog/{user}/collections/{collection_id}/items/{feature_id}"
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
