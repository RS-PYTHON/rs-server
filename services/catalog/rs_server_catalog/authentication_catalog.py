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
