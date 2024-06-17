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
from typing import Literal, Optional


def set_updated_expires_timestamp(
    item: dict,
    operation: Literal["update", "insertion"],
    expiration: Optional[datetime.datetime] = None,
    original_published: Optional[str] = None,
    original_expires: Optional[str] = None,
) -> dict:
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
    if operation == "insertion":  # We insert a new item so we create "expires" field for the first time.
        if expiration:
            item["properties"]["expires"] = expiration.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        else:
            plus_30_days = current_time + datetime.timedelta(days=30)
            item["properties"]["expires"] = plus_30_days.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    else:  # We update an existing item so we keep the original "expires" & "published" field.
        item["properties"]["expires"] = original_expires
        item["properties"]["published"] = original_published
    return item


def create_timestamps(item: dict) -> dict:
    """Set the published section timestamp during the item creation.

    Args:
        item (dict): The item to be updated.

    Returns:
        dict: The updated item.
    """
    current_time = datetime.datetime.now()
    item["properties"]["published"] = current_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return item
