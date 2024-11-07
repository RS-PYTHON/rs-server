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

import os
import re
from typing import Any

from fastapi import HTTPException
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from rs_server_common.utils.logging import Logging
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_409_CONFLICT

logger = Logging.default(__name__)

# Regular expression pattern to match 's3://path/to/file'
S3_KEY_PATTERN = r"^s3:\/\/[a-zA-Z0-9\-_.]+\/[a-zA-Z0-9\-_.\/]+$"
# Compile the pattern
s3_pattern = re.compile(S3_KEY_PATTERN)


def verify_existing_item_from_catalog(method: str, item: dict, content_id_str: str, user_collection_str: str):
    """Verify if an exisiting item from the catalog may be created or updated

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
            detail=f"Conflict error! The item {item['id']} " f"already exists in the {user_collection_str} collection",
            status_code=HTTP_409_CONFLICT,
        )
    # Protection for cases where a PUT or PATCH request is made for an item
    # that does not exist in the database.
    if method in {"PUT", "PATCH"} and not item:
        raise HTTPException(
            detail=f"The item {content_id_str} "
            f"does not exist in the {user_collection_str} collection for an update (PUT / PATCH request received)",
            status_code=HTTP_400_BAD_REQUEST,
        )


def get_s3_filename_from_asset(asset: dict) -> tuple[str, bool]:
    """
    Retrieve the S3 key from the asset content.

    During the staging process, the content of the asset should be:
        "filename": {
            "href": "s3://temp_catalog/path/to/filename",
        }

    Once the asset is inserted in the catalog, the content typically looks like this:
        "filename": {
            "alternate": {
                "s3": {
                    "href": "s3://rs-cluster-catalog/path/to/filename"
                }
            },
            "href": "https://127.0.0.1:8083/catalog/collections/user:collection_name/items/filename/download/file",
        }

    Args:
        asset (dict): The content of the asset.

    Returns:
        tuple[str, bool]: A tuple containing the full S3 path of the object and a boolean indicating
                          whether the S3 key was retrieved from the 'alternate' field.

    Raises:
        HTTPException: If the S3 key could not be loaded or is invalid.
    """
    # Attempt to retrieve the S3 key from the 'alternate.s3.href' or 'href' fields
    s3_filename = asset.get("alternate", {}).get("s3", {}).get("href")
    alternate_field = bool(s3_filename)

    if not s3_filename:
        s3_filename = asset.get("href", "")

    # Validate that the S3 key was successfully retrieved and has the correct format
    if not is_s3_path(s3_filename):
        raise HTTPException(
            detail=f"Failed to load the S3 key from the asset content {asset}",
            status_code=HTTP_400_BAD_REQUEST,
        )

    return s3_filename, alternate_field


def delete_s3_files(s3_files_to_be_deleted):
    """Used to clear specific files from temporary bucket or from catalog bucket."""
    if not s3_files_to_be_deleted:
        logger.info("No files to be deleted from bucket")
        return True
    s3_handler = get_s3_handler()
    if not s3_handler:
        logger.error("Failed to create the s3 handler when trying to delete the s3 files")
        return False

    # delete any temp file file or a file from the catalog for which the asset has been removed
    for s3_key in s3_files_to_be_deleted:
        try:
            if not is_s3_path(s3_key):
                logger.error(
                    f"The requested s3 key {s3_key} for deletion does not match the "
                    "correct S3 path pattern (s3://bucket_name/path/to/obj). Skipping",
                )
                continue
            key_array = s3_key.split("/")
            s3_handler.delete_file_from_s3(key_array[2], "/".join(key_array[3:]))
        except RuntimeError as rte:
            logger.exception(
                f"Failed to delete key {'/'.join(key_array)} from s3 bucket."
                f"Reason: {rte}. However, the process will still continue !",
            )
            continue
    return True


def is_s3_path(s3_key):
    """Function to check if a string matches the S3 pattern"""
    if not isinstance(s3_key, str):
        return False
    return bool(s3_pattern.match(s3_key))


def get_temp_bucket_name(files_s3_key: list[str]) -> str | None:
    """
    Retrieve the temporary bucket name from a list of S3 keys.

    Args:
        files_s3_key (list[str]): A list of S3 key strings.

    Returns:
        str | None: The name of the temporary S3 bucket if valid, otherwise None.

    Raises:
        HTTPException: If the S3 key does not match the expected pattern, or if multiple buckets are used.
    """
    if not files_s3_key:
        return None

    bucket_names = set()

    for s3_key in files_s3_key:
        if not is_s3_path(s3_key):
            raise RuntimeError(
                f"The S3 key '{s3_key}' does not match the correct S3 path pattern " "(s3://bucket_name/path/to/obj)",
            )
        # Extract and add the bucket name to the set
        bucket_names.add(s3_key.split("/")[2])

    if len(bucket_names) != 1:
        raise RuntimeError(f"A single temporary S3 bucket should be used in the assets: {bucket_names!r}")

    return bucket_names.pop()


def get_s3_handler():
    """Used to create the s3_handler to be used with s3 buckets."""
    try:
        s3_handler = S3StorageHandler(
            os.environ["S3_ACCESSKEY"],
            os.environ["S3_SECRETKEY"],
            os.environ["S3_ENDPOINT"],
            os.environ["S3_REGION"],
        )
    except KeyError:
        print("Failed to find s3 credentials when trying to create the s3 handler")
        return None
    except RuntimeError:
        print("Failed to create the s3 handler")
        return None

    return s3_handler


def get_token_for_pagination(items_dic: dict[Any, Any]):
    """Used to get the token to be used when calling functions from the stac-fastapi-pgstac object."""
    token = None
    for link in items_dic.get("links", []):
        if link.get("rel") == "next":
            token = link.get("href", None)
    return token
