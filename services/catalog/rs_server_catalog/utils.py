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
"""This library contains functions used in handling the user catalog."""

import os
import re
from typing import Any

from fastapi import HTTPException
from rs_server_common.utils.logging import Logging
from starlette.responses import Response
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_409_CONFLICT

logger = Logging.default(__name__)

# Constants used a bit everywhere in the Catalog
ALTERNATE_STRING = "alternate"
ISO_8601_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
CATALOG_PREFIX = os.environ.get("PREFIX_PATH", "/catalog")
DEFAULT_GEOM = {
    "type": "Polygon",
    "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]],
}
DEFAULT_BBOX = (-180.0, -90.0, 180.0, 90.0)

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
            detail=f"The item {item['id']} " f"already exists in the {user_collection_str} collection",
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


def get_token_for_pagination(items_dic: dict[Any, Any]):
    """Used to get the token to be used when calling functions from the stac-fastapi-pgstac object."""
    token = None
    for link in items_dic.get("links", []):
        if link.get("rel") == "next":
            token = link.get("href", None)
    return token


def headers_minus_content_length(response: Response) -> dict[str, str]:
    """Returns response headers without Content-Length"""
    return {k: v for k, v in response.headers.items() if k.lower() != "content-length"}


def add_prefix_link_landing_page(content: dict, url: str) -> dict:
    """
    Add the CATALOG_PREFIX to the landing page if it is not present.

    Args:
        content (dict): the landing page
        url (str): the url
    """
    for link in content["links"]:
        if "href" in link and CATALOG_PREFIX not in link["href"]:
            href = link["href"]
            url_size = len(url)
            link["href"] = href[:url_size] + CATALOG_PREFIX + href[url_size:]
    return content


def extract_owner_name_from_json_filter(json_filter: Any) -> str | None:
    """
    Scans a CQL2 JSON filter and returns the associated owner name if it contains an "owner" property.
    Owner name must be in this kind of subpart of the filter:
        "args": [{"property": "owner"}, "toto"]}

    Args:
        json_filter (Any): Filter to scan. Expected to be a dictionary (else returns None)

    Returns:
        str|None: owner name if there is one, None in any other case
    """
    if not isinstance(json_filter, dict):
        return None

    if "args" in json_filter and isinstance(json_filter["args"], list):
        if (
            len(json_filter["args"]) == 2
            and isinstance(json_filter["args"][0], dict)
            and json_filter["args"][0].get("property") == "owner"
        ):
            return json_filter["args"][1]

        for element in json_filter["args"]:
            owner_name = extract_owner_name_from_json_filter(element)
            if owner_name is not None:
                return owner_name

    return None


def extract_owner_name_from_text_filter(text_filter: str) -> str | None:
    """
    Scans a CQL2 text filter and returns the associated owner name if it contains an "owner" property.
    Owner name must be a field in this kind of filter:
        "width=2500 AND owner='toto'"

    Args:
        text_filter (str): Text filter to scan

    Returns:
        str|None: owner name if there is one, None in any other case
    """
    # Regex to isolate the content of the "owner" field in a text filter
    owner_regex = r"\bowner\s*=\s*['\"]([^'\"]+)['\"]"

    match = re.search(owner_regex, text_filter, re.IGNORECASE)

    if match:
        return match.group(1)
    return None
