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
"""This library contains functions used in handling the user catalog."""
from fastapi import HTTPException
from starlette.status import HTTP_400_BAD_REQUEST


def verify_existing_item(method: str, item: dict, content_id_str: str, user_collection_str: str):
    """Verify if an exisiting item from catalog may be created or updated

    Args:
        method (str): The HTTP method used in the request (e.g., "POST", "PUT", "PATCH").
        item (dict): The item from the catalog to check.
        content_id_str (str): The name of the item, used for generating an error message
        user_collection_str (str): The collection identifier including the user.

    Raises:
        HTTPException: If a POST request is made for an existing item,
                       or if a PUT/PATCH request is made for a non-existent item.
    """

    # Protection for cases where a POST request attempts to add an
    # item with a name that already exists in the database.
    if method == "POST" and item:
        raise HTTPException(
            detail=f"Conflict error! The item {item['id']} \
already exists in the {user_collection_str} collection",
            status_code=HTTP_400_BAD_REQUEST,
        )
    # Protection for cases where a PUT or PATCH request is made for an item
    # that does not exist in the database.
    if method in {"PUT", "PATCH"} and not item:
        raise HTTPException(
            detail=f"The item {content_id_str} \
does not exist in the {user_collection_str} collection for an update (PUT / PATCH request received)",
            status_code=HTTP_400_BAD_REQUEST,
        )
