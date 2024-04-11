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
