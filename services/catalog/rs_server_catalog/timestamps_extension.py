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

"""Contains all functions for timestamps extension management."""

import datetime

from rs_server_common.s3_storage_handler.s3_storage_config import (
    get_expiration_delay_from_config,
)

ISO_8601_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def set_timestamps_for_creation(item: dict) -> dict:
    """This function set the timestamps for an item creation.
    It will update the 'updated' and 'published' timestamps.

    Args:
        item (dict): The item to be created.

    Returns:
        dict: The updated item.
    """
    item = set_updated_timestamp_to_now(item)
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
    item = set_updated_timestamp_to_now(item)
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
    item = set_updated_timestamp_to_now(item)
    item["properties"].setdefault("expires", original_expires)
    item["properties"].setdefault("published", original_published)
    return item


def set_updated_timestamp_to_now(item: dict) -> dict:
    """Updates the 'updated' timestamp of the given item with the current time.

    Args:
        item (dict): The item to be updated.

    Returns:
        dict: The updated item.
    """
    current_time = datetime.datetime.now()
    item["properties"]["updated"] = current_time.strftime(ISO_8601_FORMAT)
    return item
