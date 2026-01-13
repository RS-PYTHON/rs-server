# Copyright 2023-2026 Airbus, CS Group
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

import os

import botocore
from rs_server_catalog.authentication_catalog import get_authorisation
from rs_server_catalog.utils import get_s3_handler
from rs_server_common.s3_storage_handler.s3_storage_config import (
    get_bucket_name_from_config,
)
from rs_server_common.utils import utils2
from rs_server_common.utils.logging import Logging
from starlette.status import (
    HTTP_302_FOUND,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

ALTERNATE_STRING = "alternate"
PRESIGNED_URL_EXPIRATION_TIME = int(os.environ.get("RSPY_PRESIGNED_URL_EXPIRATION_TIME", "1800"))  # 30 minutes

logger = Logging.default(__name__)


def generate_presigned_url(content, path):
    """This function is used to generate a time-limited download url"""
    # Assume that pgstac already selected the correct asset id
    # just check type, generate and return url
    path_splitted = path.split("/")
    asset_id = path_splitted[-1]
    item_id = path_splitted[-3]
    # Retrieve bucket name from config using what's in content
    item_owner = content["properties"].get("owner", "*")
    item_collection = content.get("collection", "*").removeprefix(f"{item_owner}_")
    item_eopf_type = content["properties"].get("eopf:type", "*")
    bucket_name = get_bucket_name_from_config(item_owner, item_collection, item_eopf_type)
    try:
        s3_path = (
            content["assets"][asset_id]["href"]
            .replace(
                f"s3://{bucket_name}",
                "",
            )
            .lstrip("/")
        )
    except KeyError:
        return f"Failed to find asset named '{asset_id}' from item '{item_id}'", HTTP_404_NOT_FOUND
    try:
        s3_handler = get_s3_handler()
        if not s3_handler:
            raise utils2.log_http_exception(
                logger=logger,
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to find s3 credentials",
            )
        response = s3_handler.s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": s3_path},
            ExpiresIn=PRESIGNED_URL_EXPIRATION_TIME,
        )
    except botocore.exceptions.ClientError:
        return "Failed to generate presigned url", HTTP_400_BAD_REQUEST
    return response, HTTP_302_FOUND


def manage_all_collections(collections: dict, auth_roles: list, user_login: str) -> list[dict]:
    """Return the list of all collections accessible by the user calling it.

    Args:
        collections (dict): List of all collections.
        auth_roles (list): List of roles of the api-key.
        user_login (str): The api-key owner.

    Returns:
        dict: The list of all collections accessible by the user.
    """
    # Test user authorization on each collection
    accessible_collections = [
        requested_col
        for requested_col in collections
        if get_authorisation(
            [requested_col["id"]],
            auth_roles,
            "read",
            requested_col["owner"],
            user_login,
            owner_prefix=True,
        )
    ]

    # Return results, sorted by <owner>_<collection_id>
    return sorted(accessible_collections, key=lambda col: col["id"])
