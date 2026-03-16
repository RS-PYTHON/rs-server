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

"""Module handling all operations on S3 bucket."""

import os
import traceback

import botocore
from fastapi import HTTPException
from rs_server_catalog.utils import verify_existing_item_from_catalog
from rs_server_common.s3_storage_handler.s3_storage_config import (
    get_bucket_name_from_config,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import S3Credentials
from starlette.requests import Request
from starlette.status import (
    HTTP_302_FOUND,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

PRESIGNED_URL_EXPIRATION_TIME = int(os.environ.get("RSPY_PRESIGNED_URL_EXPIRATION_TIME", "1800"))  # 30 minutes

logger = Logging.default(__name__)


class S3Manager:
    """Tool class to handle all operations on S3 bucket."""

    def __init__(self, s3_credentials: S3Credentials):
        """
        Constructor.

        Args:
            s3_credentials: S3 credentials
        """
        self.s3_handler: S3StorageHandler = self._get_s3_handler(s3_credentials)
        # If we are in local mode, operations on S3 bucket will be skipped
        self.is_catalog_local_mode = int(os.environ.get("RSPY_LOCAL_CATALOG_MODE", 0)) == 1

    def _get_s3_handler(self, s3_credentials: S3Credentials) -> S3StorageHandler:
        """
        Used to create the s3_handler to be used with s3 buckets.

        Args:
            s3_credentials: S3 credentials
        Returns:
            S3StorageHandler: S3 handler
        """
        try:
            s3_handler = S3StorageHandler(s3_credentials)
        except RuntimeError:
            logger.warning(f"Failed to create the s3 handler: {traceback.format_exc()}")
            return None

        return s3_handler

    def clear_catalog_bucket(self, content: dict) -> None:
        """Used to clear specific files from catalog bucket.

        Args:
            content (dict): Files to delete
            s3_handler (S3StorageHandler): S3 handler to use. If None given, will do nothing
        """
        if self.is_catalog_local_mode or (not hasattr(content, "get")):
            return
        for asset in content.get("assets", {}):
            # Retrieve bucket name from config using what's in content
            item_owner = content["properties"].get("owner", "*")
            item_collection = content.get("collection", "*").removeprefix(f"{item_owner}_")
            item_eopf_type = content["properties"].get("eopf:type", "*")
            bucket_name = get_bucket_name_from_config(item_owner, item_collection, item_eopf_type)
            # For catalog bucket, data is already stored into href field (from an asset)
            file_key = content["assets"][asset]["href"]
            if not int(os.environ.get("RSPY_LOCAL_CATALOG_MODE", 0)):  # don't delete files if we are in local mode
                self.s3_handler.delete_key_from_s3(bucket_name, file_key)

    def check_s3_key(self, item: dict, asset_name: str, s3_key: str) -> tuple[bool, int]:
        """Check if the given S3 key exists and matches the expected path.

        Args:
            item (dict): The item from the catalog (if it does exist) containing the asset.
            asset_name (str): The name of the asset to check.
            s3_key (str): The S3 key path to check against.

        Returns:
            bool: True if the S3 key is valid and exists, otherwise False.
            NOTE: Don't mind if we have RSPY_LOCAL_CATALOG_MODE set to ON (meaning self.s3_handler is None)

        Raises:
            HTTPException: If the s3_handler is not available, if S3 paths cannot be retrieved,
                        if the S3 paths do not match, or if there is an error checking the key.
        """
        if not item or self.is_catalog_local_mode:
            return False, -1
        # update an item
        existing_asset = item["assets"].get(asset_name)
        if not existing_asset:
            return False, -1

        # check if the new s3_href is the same as the existing one
        try:
            item_s3_path = existing_asset["href"]
        except KeyError as exc:
            raise HTTPException(
                detail=f"Failed to get the s3 path for the asset {asset_name}",
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc
        if item_s3_path != s3_key:
            raise HTTPException(
                detail=(
                    f"Received an updated path for the asset {asset_name} of item {item['id']}. "
                    f"The current path is {item_s3_path}, and the new path is {s3_key}. "
                    "However, changing an existing path of an asset is not allowed."
                ),
                status_code=HTTP_400_BAD_REQUEST,
            )
        s3_key_array = s3_key.split("/")
        bucket = s3_key_array[2]
        key_path = "/".join(s3_key_array[3:])

        # check the presence of the key
        try:
            s3_key_exists, size = self.s3_handler.check_s3_key_on_bucket(bucket, key_path)
            if not s3_key_exists:
                return False, -1
                # raise HTTPException(
                #     detail=f"The s3 key {s3_key} should exist on the bucket, but it couldn't be checked",
                #     status_code=HTTP_400_BAD_REQUEST,
                # )
            return True, size
        except RuntimeError as rte:
            raise HTTPException(
                detail=f"When checking the presence of the {s3_key} key, an error has been raised: {rte}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from rte

    def update_stac_item_publication(  # pylint: disable=too-many-locals,too-many-branches,too-many-nested-blocks
        self,
        content: dict,
        request: Request,
        request_ids: dict,
        item: dict,
    ) -> dict:
        """Update the JSON body of a feature with new stac extensions and owner information.

        Args:
            content (dict): The content to update.
            request (Request): The HTTP request object.
            request_ids (dict): IDs associated to the given request
            item (dict): The item from the catalog (if exists) to update.

        Returns:
            dict: The updated content.
            list: List of files to delete from the S3 bucket


        """
        collection_ids = request_ids.get("collection_ids", [])
        user = request_ids.get("owner_id")
        logger.debug(f"Update item for user: {user}")
        if not isinstance(collection_ids, list) or not collection_ids or not user:
            raise HTTPException(
                detail="Failed to get the user or the name of the collection!",
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            )
        collection_id = collection_ids[0]
        verify_existing_item_from_catalog(request.method, item, content.get("id", "Unknown"), f"{user}_{collection_id}")

        # 3 - include new stac extensions if not present
        for new_stac_extension in [
            "https://home.rs-python.eu/ownership-stac-extension/v1.1.0/schema.json",
            "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json",
            "https://stac-extensions.github.io/file/v2.1.0/schema.json",
        ]:
            if new_stac_extension not in content["stac_extensions"]:
                content["stac_extensions"].append(new_stac_extension)

        # 5 - add owner data
        content["properties"].update({"owner": user})
        content.update({"collection": f"{user}_{collection_id}"})
        logger.debug(f"The updated item for user: {user} ended")
        return content

    def generate_presigned_url(self, content: dict, path: str) -> tuple[str, int]:
        """This function is used to generate a time-limited download url

        Args:
            content (dict): STAC description of the item to generate an URL for
            path (str): Current path to this object

        Returns:
            str: Presigned URL
            int: HTTP return code
        """
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
            s3_path = content["assets"][asset_id]["href"].removeprefix(f"s3://{bucket_name}/")
        except KeyError:
            return f"Failed to find asset named '{asset_id}' from item '{item_id}'", HTTP_404_NOT_FOUND
        try:
            if not self.s3_handler:
                raise HTTPException(
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to find s3 credentials",
                )
            response = self.s3_handler.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name, "Key": s3_path},
                ExpiresIn=PRESIGNED_URL_EXPIRATION_TIME,
            )
        except botocore.exceptions.ClientError:
            return "Failed to generate presigned url", HTTP_400_BAD_REQUEST
        return response, HTTP_302_FOUND

    def check_if_item_can_be_published(self, content: dict) -> bool:
        """
        Check if all assets of a given catalog item exist on S3 and are valid for publishing.

        Iterates through each asset in the `content["assets"]` dictionary and verifies
        the presence of the S3 key (or folder/prefix) using `check_s3_key`. Logs the
        results and any errors encountered. Returns True only if all assets exist;
        returns False if at least one asset is missing or cannot be verified.

        Args:
            content (dict): A catalog item dictionary containing asset information
                            under the "assets" key.

        Returns:
            bool: True if all assets exist on S3 and can be published, False otherwise.

        Notes:
            - Handles exceptions raised by `check_s3_key` and logs errors without stopping iteration.
            - For folder/prefix assets, the size returned is ignored (-1), but existence is still validated.
        """
        # (don't do anything if in local mode)
        if self.is_catalog_local_mode:
            return True

        collection_id = content.get("collection")
        item_eopf_type = content["properties"].get("eopf:type", "*")
        user = content["properties"].get("owner", "*")
        bucket_name = get_bucket_name_from_config(user, collection_id, item_eopf_type)
        exist_list = []
        for asset_name, asset_info in content.get("assets", {}).items():
            exists = False
            if s3_key := asset_info.get("href"):
                if bucket_name not in s3_key:
                    logger.error(
                        f"Asset: {asset_name}, The s3 key {s3_key} should contain the bucket name {bucket_name}",
                    )
                    exist_list.append(False)
                    continue
                try:
                    exists, size = self.check_s3_key(content, asset_name, s3_key)
                    logger.info(f"Asset: {asset_name}, Found on bucket: {exists}, Size: {size}")
                except HTTPException as e:
                    logger.error(f"Asset: {asset_name}, Error: {e.detail}")
            exist_list.append(exists)
        return all(exist_list)
