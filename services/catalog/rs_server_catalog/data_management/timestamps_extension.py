# Copyright 2023-2025 Airbus, CS Group
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

"""Contains all functions for timestamps extension management."""

import datetime

from rs_server_catalog.utils import ISO_8601_FORMAT
from rs_server_common.s3_storage_handler.s3_storage_config import (
    get_expiration_delay_from_config,
)


def set_timestamps_for_creation(item: dict) -> dict:
    """This function set the timestamps for an item creation.
    It will update the 'updated' and 'published' timestamps.

    Args:
        item (dict): The item to be created.

    Returns:
        dict: The updated item.
    """
    item = set_updated_timestamp_to_now(item, is_item=True)
    item["properties"]["published"] = item["properties"]["updated"]
    return item


def set_timestamps_for_insertion(item: dict) -> dict:
    """This function set the timestamps for an item insertion.
    It will update the 'updated' and 'expires' timestamps.

    Args:
        item (dict): The item to be updated.

    Returns:
        dict: The updated item.
    """
    item = set_updated_timestamp_to_now(item, is_item=True)
    item_owner = item["properties"].get("owner", "*")
    item_collection = item.get("collection", "*").removeprefix(f"{item_owner}_")
    item_eopf_type = item["properties"].get("eopf:type", "*")
    expiration_range = get_expiration_delay_from_config(item_owner, item_collection, item_eopf_type)
    expiration_date = datetime.datetime.now() + datetime.timedelta(days=expiration_range)
    item["properties"].setdefault("expires", expiration_date.strftime(ISO_8601_FORMAT))
    return item


def set_timestamps_for_update(item: dict, original_published: str, original_expires: str) -> dict:
    """This function set the timestamps for an item update.
    It will update the 'updated' timestamp along with the 'expires' and 'published' ones
    with the values given.

    Args:
        item (dict): The item to be updated.
        original_published (str): Original 'published' timestamp to set.
        original_expires (str): Original 'expires' timestamp to set.

    Returns:
        dict: The updated item.
    """
    item = set_updated_timestamp_to_now(item, is_item=True)
    item["properties"].setdefault("expires", original_expires)
    item["properties"].setdefault("published", original_published)
    return item


def set_timestamps_to_collection(collection: dict, original_created: str = "") -> dict:
    """
    Sets values for the 'created' and 'updated' fields of a Collection.
    If there is already a 'created' field, this one is skipped.
    If there is no 'created' field but an 'original_created' is given, the 'original_created'
    value is taken, otherwise the value given is the one of the 'updated' field.

    Args:
        collection (dict): The collection to update
        original_created (str): Existing "created" value, if any (optional)

    Returns:
        dict: The updated collection
    """
    collection = set_updated_timestamp_to_now(collection, is_item=False)
    if "created" not in collection:
        collection["created"] = original_created or collection["updated"]
    return collection


def set_updated_timestamp_to_now(stac_object: dict, is_item: bool = True) -> dict:
    """Updates the 'updated' timestamp of the given object with the current time.
    If the object is an Item, the 'updated' field is located in the 'properties', otherwise
    it is at the root of the dictionary.

    Args:
        stac_object (dict): The object to be updated.

    Returns:
        dict: The updated object.
    """
    current_time = datetime.datetime.now().strftime(ISO_8601_FORMAT)
    if is_item:
        stac_object["properties"]["updated"] = current_time
    else:
        stac_object["updated"] = current_time
    return stac_object
