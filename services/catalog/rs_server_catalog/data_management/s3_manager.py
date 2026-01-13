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

from fastapi import HTTPException
from rs_server_catalog.utils import (
    get_s3_filename_from_asset,
    get_s3_handler,
    get_temp_bucket_name,
    verify_existing_item_from_catalog,
)
from rs_server_common.s3_storage_handler.s3_storage_config import (
    get_bucket_name_from_config,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3StorageHandler,
    TransferFromS3ToS3Config,
)
from rs_server_common.utils import utils2
from rs_server_common.utils.logging import Logging
from starlette.requests import Request
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

ALTERNATE_STRING = "alternate"

logger = Logging.default(__name__)


def log_http_exception(*args, **kwargs) -> type[HTTPException]:
    """Log error and return an HTTP exception to be raised by the caller"""
    return utils2.log_http_exception(logger, *args, **kwargs)


class S3Manager:

    def __init__(self):
        self.s3_handler: S3StorageHandler = None
        # Retrieve handler only if we are not in local mode
        # If we are in local mode, operations on S3 bucket will be skipped
        if not int(os.environ.get("RSPY_LOCAL_CATALOG_MODE", 0)):
            self.s3_handler = get_s3_handler()

    def clear_catalog_bucket(self, content: dict) -> None:
        """Used to clear specific files from catalog bucket.

        Args:
            content (dict): Files to delete
            s3_handler (S3StorageHandler): S3 handler to use. If None given, will do nothing
        """
        if not self.s3_handler:
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
                self.s3_handler.delete_file_from_s3(bucket_name, file_key)

    def check_s3_key(self, item: dict, asset_name: str, s3_key):
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
        if not item or not self.s3_handler:
            return False, -1
        # update an item
        existing_asset = item["assets"].get(asset_name)
        if not existing_asset:
            return False, -1

        # check if the new s3_href is the same as the existing one
        try:
            item_s3_path = existing_asset["href"]
        except KeyError as exc:
            raise log_http_exception(
                detail=f"Failed to get the s3 path for the asset {asset_name}",
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            ) from exc
        if item_s3_path != s3_key:
            raise log_http_exception(
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
                raise log_http_exception(
                    detail=f"The s3 key {s3_key} should exist on the bucket, but it couldn't be checked",
                    status_code=HTTP_400_BAD_REQUEST,
                )
            return True, size
        except RuntimeError as rte:
            raise log_http_exception(
                detail=f"When checking the presence of the {s3_key} key, an error has been raised: {rte}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from rte

    def s3_bucket_handling(self, bucket_name: str, files_s3_key: list[str], item: dict, request: Request) -> list:
        """Handle the transfer and deletion of files in S3 buckets.

        Args:
            files_s3_key (list[str]): List of S3 keys for the files to be transfered.
            item (dict): The catalog item from which all the remaining assets should be deleted.
            request (Request): The request object, used to determine the request method.

        Raises:
            HTTPException: If there are errors during the S3 transfer or deletion process.
        """
        if not self.s3_handler or not files_s3_key:
            logger.debug(f"s3_bucket_handling: nothing to do: {self.s3_handler} | {files_s3_key}")
            return []

        try:
            s3_files_to_be_deleted = []
            # get the temporary bucket name, there should be one only in the set
            temp_bucket_name = get_temp_bucket_name(files_s3_key)
            # now, remove the s3://temp_bucket_name for each s3_key
            for idx, s3_key in enumerate(files_s3_key):
                # build the list with files to be deleted from the temporary bucket
                s3_files_to_be_deleted.append(s3_key)
                files_s3_key[idx] = s3_key.replace(f"s3://{temp_bucket_name}", "")

            err_message = f"Failed to transfer file(s) from '{temp_bucket_name}' bucket to \
'{bucket_name}' catalog bucket!"
            config = TransferFromS3ToS3Config(
                files_s3_key,
                temp_bucket_name,
                bucket_name,
                copy_only=True,
                max_retries=3,
            )

            failed_files = self.s3_handler.transfer_from_s3_to_s3(config)

            if failed_files:
                s3_files_to_be_deleted.clear()
                raise log_http_exception(
                    detail=f"{err_message} {failed_files}",
                    status_code=HTTP_400_BAD_REQUEST,
                )
            # For a PUT request, all new assets are transferred (as described above).
            # Any asset that already exists in the catalog from a previous POST request
            # but is not included in the current request will be deleted.
            # In the case of a PATCH request (not yet implemented), no assets should be deleted.
            if item and request.method == "PUT":
                for asset in item["assets"]:
                    s3_files_to_be_deleted.append(item["assets"][asset]["href"])
            return s3_files_to_be_deleted
        except KeyError as kerr:
            raise log_http_exception(
                detail=f"{err_message} Failed to find S3 credentials.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from kerr
        except RuntimeError as rte:
            raise log_http_exception(detail=f"{err_message} Reason: {rte}", status_code=HTTP_400_BAD_REQUEST) from rte

    def update_stac_item_publication(  # pylint: disable=too-many-locals,too-many-branches,too-many-nested-blocks
        self,
        content: dict,
        request: Request,
        request_ids: dict,
        item: dict,
    ) -> tuple[dict, list]:
        """Update the JSON body of a feature push to the catalog.

        Args:
            content (dict): The content to update.
            request (Request): The HTTP request object.
            item (dict): The item from the catalog (if exists) to update.

        Returns:
            dict: The updated content.

        Raises:
            HTTPException: If there are errors in processing the request, such as missing collection name,
                        invalid S3 bucket, or failed file transfers.
        """
        collection_ids = request_ids.get("collection_ids", [])
        user = request_ids.get("owner_id")
        logger.debug(f"Update item for user: {user}")
        if not isinstance(collection_ids, list) or not collection_ids or not user:
            raise log_http_exception(
                detail="Failed to get the user or the name of the collection!",
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            )
        collection_id = collection_ids[0]
        verify_existing_item_from_catalog(request.method, item, content.get("id", "Unknown"), f"{user}_{collection_id}")

        item_eopf_type = content["properties"].get("eopf:type", "*")
        bucket_name = get_bucket_name_from_config(user, collection_id, item_eopf_type)

        files_s3_key = []
        # 1 - update assets href
        for asset in content["assets"]:
            s3_filename, alternate_field = get_s3_filename_from_asset(content["assets"][asset])
            if alternate_field:
                if not item:
                    # the asset should be already in the catalog from a previous POST/PUT request
                    raise log_http_exception(
                        detail=(f"The item that contains asset '{asset}' does not exist in the catalog but it should "),
                        status_code=HTTP_400_BAD_REQUEST,
                    )
            # else:
            # if alternate_key is missing, it indicates the request originates from the staging process.
            # In this case, the file should not be deleted from the temp bucket — it's already stored in the
            # final catalog bucket, so no action is needed.

            logger.debug(f"HTTP request add/update asset: {s3_filename!r}")
            fid = s3_filename.rsplit("/", maxsplit=1)[-1]
            if fid != asset:
                raise log_http_exception(
                    detail=(
                        f"Invalid structure for the asset '{asset}'. The name of the asset "
                        f"should be the filename, that is {fid} "
                    ),
                    status_code=HTTP_400_BAD_REQUEST,
                )
            # 2 - update alternate href to define catalog s3 bucket
            try:
                old_bucket_arr = s3_filename.split("/")
                old_bucket = old_bucket_arr[2]
                old_bucket_arr[2] = bucket_name
                s3_key = "/".join(old_bucket_arr)
                # Check if the S3 key exists
                s3_key_exists, _ = self.check_s3_key(item, asset, s3_key)
                if not s3_key_exists:
                    # update the S3 path to use the catalog bucket
                    # add also the file:size and file:local_path fields
                    content["assets"][asset].update({"href": s3_key, "file:local_path": "/".join(old_bucket_arr[-2:])})
                    # update the 'href' key with the download link and create the alternate field
                    https_link = f"https://{request.url.netloc}/catalog/\
collections/{user}:{collection_id}/items/{request_ids['item_id']}/download/{asset}"
                    content["assets"][asset].update({ALTERNATE_STRING: {"https": {"href": https_link}}})

                    # copy the key only if it isn't already in the final catalog bucket
                    # (don't do anything if in local mode)
                    if not int(os.environ.get("RSPY_LOCAL_CATALOG_MODE", 0)):
                        s3_key_exists, size = self.s3_handler.check_s3_key_on_bucket(
                            bucket_name,
                            "/".join(old_bucket_arr[3:]),
                        )
                        if not s3_key_exists:
                            files_s3_key.append(s3_filename)
                            if "file:size" not in content["assets"][asset]:
                                _, size = self.s3_handler.check_s3_key_on_bucket(
                                    old_bucket,
                                    "/".join(old_bucket_arr[3:]),
                                )
                        if "file:size" not in content["assets"][asset] and size != -1:
                            content["assets"][asset]["file:size"] = size
                        logger.debug(f"file:size = {size}")

                elif request.method == "PUT":
                    # remove the asset from the item, all assets that remain shall
                    # be deleted from the catalog s3 bucket later on
                    item["assets"].pop(asset)
            except (IndexError, AttributeError, KeyError, RuntimeError) as exc:
                raise log_http_exception(
                    detail=f"Failed to handle the s3 level. Reason: {exc}",
                    status_code=HTTP_400_BAD_REQUEST,
                ) from exc

        # 3 - include new stac extensions if not present
        for new_stac_extension in [
            "https://home.rs-python.eu/ownership-stac-extension/v1.1.0/schema.json",
            "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json",
            "https://stac-extensions.github.io/file/v2.1.0/schema.json",
        ]:
            if new_stac_extension not in content["stac_extensions"]:
                content["stac_extensions"].append(new_stac_extension)

        # 4 - bucket handling
        s3_files_to_be_deleted = self.s3_bucket_handling(bucket_name, files_s3_key, item, request)

        # 5 - add owner data
        content["properties"].update({"owner": user})
        content.update({"collection": f"{user}_{collection_id}"})
        return content, s3_files_to_be_deleted
