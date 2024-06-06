"""Contains all functions for timestamps extension management."""

import datetime


def set_updated_expires_timestamp(item: any, expiration: datetime.datetime = None) -> dict:
    """This function set the timestamps for an item.
    If we want to insert a new item, it will update
    The sections "updated", and "expires".
    If we want to update an existing item, it will just
    update the section "updated".

    Args:
        item (dict): The item to be updated.
        expiration (datetime, optional): The expiration date. Defaults to None.

    Returns:
        dict: The updated item.
    """
    current_time = datetime.datetime.now()
    item["properties"]["updated"] = current_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if expiration:
        item["properties"]["expires"] = expiration.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    else:
        plus_30_days = current_time + datetime.timedelta(days=30)
        item["properties"]["expires"] = plus_30_days.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return item


def create_timestamps(item: any) -> dict:
    """Set the published section timestamp during the item creation.

    Args:
        item (dict): The item to be updated.

    Returns:
        dict: The updated item.
    """
    current_time = datetime.datetime.now()
    item["properties"]["published"] = current_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return item
