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

"""A BaseHTTPMiddleware to handle the user multi catalog.

The stac-fastapi software doesn't handle multi catalog.
In the rs-server we need to handle user-based catalogs.

The rs-server uses only one catalog but the collections are prefixed by the user name.
The middleware is used to hide this mechanism.

The middleware:
* redirect the user-specific request to the common stac api endpoint
* modifies the request to add the user prefix in the collection name
* modifies the response to remove the user prefix in the collection name
* modifies the response to update the links.
"""

import getpass
import json
import os
import re
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import botocore
from fastapi import HTTPException
from pygeofilter.ast import Attribute, Equal, Like, Node
from pygeofilter.parsers.cql2_json import parse as parse_cql2_json
from pygeofilter.parsers.ecql import parse as parse_ecql
from rs_server_catalog import timestamps_extension
from rs_server_catalog.authentication_catalog import get_authorisation
from rs_server_catalog.landing_page import (
    add_prefix_link_landing_page,
    manage_landing_page,
)
from rs_server_catalog.search import (
    search_endpoint_get,
    search_endpoint_in_collection_get,
    search_endpoint_in_collection_post,
    search_endpoint_post,
)
from rs_server_catalog.user_handler import (
    add_user_prefix,
    filter_collections,
    remove_user_from_collection,
    remove_user_from_feature,
    reroute_url,
)
from rs_server_catalog.utils import (
    get_s3_filename_from_asset,
    get_temp_bucket_name,
    is_s3_path,
    verify_existing_item_from_catalog,
)
from rs_server_common import settings as common_settings
from rs_server_common.authentication import oauth2
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3StorageHandler,
    TransferFromS3ToS3Config,
)
from rs_server_common.utils.logging import Logging
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.types.errors import NotFoundError
from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_302_FOUND,
    HTTP_307_TEMPORARY_REDIRECT,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

PRESIGNED_URL_EXPIRATION_TIME = int(os.environ.get("RSPY_PRESIGNED_URL_EXPIRATION_TIME", "1800"))  # 30 minutes
CATALOG_BUCKET = os.environ.get("RSPY_CATALOG_BUCKET", "rs-cluster-catalog")

# pylint: disable=too-many-lines
logger = Logging.default(__name__)


class UserCatalog:  # pylint: disable=too-many-public-methods
    """The user catalog middleware handler."""

    client: CoreCrudClient

    def __init__(self, client: CoreCrudClient):
        """Constructor, called from the middleware"""

        self.s3_handler: S3StorageHandler = None
        self.request_ids: dict[Any, Any] = {}
        self.client = client
        self.s3_keys_to_be_deleted: list[str] = []

    def remove_user_from_objects(self, content: dict, user: str, object_name: str) -> dict:
        """Remove the user id from the object.

        Args:
            content (dict): The response content from the middleware
            'call_next' loaded in json format.
            user (str): The user id to remove.
            object_name (str): Precise the object type in the content.
            It can be collections or features.

        Returns:
            dict: The content with the user id removed.
        """
        objects = content[object_name]
        nb_objects = len(objects)
        for i in range(nb_objects):
            if object_name == "collections":
                objects[i] = remove_user_from_collection(objects[i], user)
            else:
                objects[i] = remove_user_from_feature(objects[i], user)
        return content

    def clear_unnecessary_s3_files(self):
        """Used to clear specific files from temporary bucket and from catalog bucket if needed."""
        if not self.s3_handler:
            return
        # delete any temp file file or a file from the catalog for which the asset has been removed
        for s3_key in self.s3_keys_to_be_deleted:
            try:
                if not is_s3_path(s3_key):
                    raise HTTPException(
                        detail=f"The s3 key {s3_key} does not match with a correct s3"
                        "path pattern (s3://bucket_name/path/to/obj)",
                        status_code=HTTP_400_BAD_REQUEST,
                    )
                key_array = s3_key.split("/")
                self.s3_handler.delete_file_from_s3(key_array[2], "/".join(key_array[3:]))
            except RuntimeError as rte:
                logger.exception(
                    f"Failed to delete key {'/'.join(key_array)} from s3 bucket."
                    f"Reason: {rte}. The process will continue though !",
                )
        self.s3_keys_to_be_deleted.clear()

    def clear_catalog_bucket(self, content: dict):
        """Used to clear specific files from catalog bucket."""
        if not self.s3_handler:
            return
        for asset in content.get("assets", {}):
            # For catalog bucket, data is already stored into alternate:s3:href
            file_key = content["assets"][asset]["alternate"]["s3"]["href"]
            if not int(os.environ.get("RSPY_LOCAL_CATALOG_MODE", 0)):  # don't delete files if we are in local mode
                self.s3_handler.delete_file_from_s3(CATALOG_BUCKET, file_key)

    def adapt_object_links(self, my_object: dict, user: str) -> dict:
        """adapt all the links from a collection so the user can use them correctly

        Args:
            object (dict): The collection
            user (str): The user id

        Returns:
            dict: The collection passed in parameter with adapted links
        """
        links = my_object["links"]
        for j, link in enumerate(links):
            link_parser = urlparse(link["href"])
            if "properties" in my_object:  # If my_object is an item
                new_path = add_user_prefix(link_parser.path, user, my_object["collection"], my_object["id"])
            else:  # If my_object is a collection
                new_path = add_user_prefix(link_parser.path, user, my_object["id"])
            links[j]["href"] = link_parser._replace(path=new_path).geturl()
        return my_object

    def adapt_links(self, content: dict, user: str, collection_id: str, object_name: str) -> dict:
        """adapt all the links that are outside from the collection section

        Args:
            content (dict): The response content from the middleware
            'call_next' loaded in json format.
            user (str): The user id.

        Returns:
            dict: The content passed in parameter with adapted links
        """
        links = content["links"]
        for i, link in enumerate(links):
            link_parser = urlparse(link["href"])
            new_path = add_user_prefix(link_parser.path, user, collection_id)
            links[i]["href"] = link_parser._replace(path=new_path).geturl()
        for i in range(len(content[object_name])):
            content[object_name][i] = self.adapt_object_links(content[object_name][i], user)
        return content

    async def get_item_from_collection(self, request: Request):
        """Get an item from the collection.

        Args:
            request (Request): The request object.

        Returns:
            Optional[Dict]: The item from the collection if found, else None.
        """
        try:
            item = await self.client.get_item(
                item_id=self.request_ids["item_id"],
                collection_id=f"{self.request_ids['owner_id']}_{self.request_ids['collection_id']}",
                request=request,
            )
            return item
        except NotFoundError:
            logger.info(
                f"The element {self.request_ids['item_id']} does not \
exist in collection {self.request_ids['owner_id']}_{self.request_ids['collection_id']}",
            )
            return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception(f"Exception: {e}")
            raise HTTPException(
                detail=f"Exception when trying to get the item {item['id']} \
from the the {self.request_ids['owner_id']}_{self.request_ids['collection_id']} collection",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

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
            return False
        # update an item
        existing_asset = item["assets"].get(asset_name, None)
        if not existing_asset:
            return False

        # check if the new s3_href is the same as the existing one
        try:
            item_s3_path = existing_asset["alternate"]["s3"]["href"]
        except KeyError as exc:
            raise HTTPException(
                detail=f"Could not get the s3 path for the asset {asset_name}",
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
            if not self.s3_handler.check_s3_key_on_bucket(bucket, key_path):
                raise HTTPException(
                    detail=f"The s3 key {s3_key} should exist on the bucket, but it couldn't be checked",
                    status_code=HTTP_400_BAD_REQUEST,
                )
            return True
        except RuntimeError as rte:
            raise HTTPException(
                detail=f"When checking the presence of the {s3_key} key, an error has been raised: {rte}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from rte

    def s3_bucket_handling(self, files_s3_key: list[str], item: dict, request: Request) -> None:
        """Handle the transfer and deletion of files in S3 buckets.

        Args:
            files_s3_key (list[str]): List of S3 keys for the files to be transfered.
            item (dict): The catalog item from which all the remaining assets should be deleted.
            request (Request): The request object, used to determine the request method.

        Raises:
            HTTPException: If there are errors during the S3 transfer or deletion process.
        """
        if not self.s3_handler or not files_s3_key:
            return

        try:
            temp_bucket_name = get_temp_bucket_name(files_s3_key)
            # now remove the s3://temp_bucket_name for each s3_key
            for idx, s3_key in enumerate(files_s3_key):
                files_s3_key[idx] = s3_key.replace(f"s3://{temp_bucket_name}", "")

            err_message = f"Failed to transfer file(s) from '{temp_bucket_name}' bucket to \
'{CATALOG_BUCKET}' catalog bucket!"
            config = TransferFromS3ToS3Config(
                files_s3_key,
                temp_bucket_name,
                CATALOG_BUCKET,
                copy_only=True,
                max_retries=3,
            )

            failed_files = self.s3_handler.transfer_from_s3_to_s3(config)

            if failed_files:
                raise HTTPException(
                    detail=f"{err_message} {failed_files}",
                    status_code=HTTP_400_BAD_REQUEST,
                )
            # In case of the PUT request, all the new assets are transfered (see up)
            # Any existing asset in the item (already in the catalog from a previous POST request)
            # but not found in this request is deleted
            # If a PATCH request is received (not yet implemented) do not delete anything
            if item and request.method == "PUT":
                for asset in item["assets"]:
                    self.s3_keys_to_be_deleted.append(item["assets"][asset]["alternate"]["s3"]["href"])
        except KeyError as kerr:
            raise HTTPException(
                detail=f"{err_message} Could not find S3 credentials.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from kerr
        except RuntimeError as rte:
            raise HTTPException(detail=f"{err_message} Reason: {rte}", status_code=HTTP_400_BAD_REQUEST) from rte

    def update_stac_item_publication(  # pylint: disable=too-many-locals
        self,
        content: dict,
        request: Request,
        item: dict,
    ) -> Any:
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
        if not int(os.environ.get("RSPY_LOCAL_CATALOG_MODE", 0)):  # don't move files if we are in local mode
            self.s3_handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            )

        collection_id = self.request_ids.get("collection_id", None)
        user = self.request_ids.get("owner_id", None)
        if not collection_id or not user:
            raise HTTPException(
                detail="Could not get the user or the name of the collection!",
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            )
        verify_existing_item_from_catalog(request.method, item, content.get("id", "Unknown"), f"{user}_{collection_id}")

        files_s3_key = []
        # 1 - update assets href
        for asset in content["assets"]:
            s3_filename, alternate_field = get_s3_filename_from_asset(content["assets"][asset])
            if alternate_field:
                if not item:
                    # the asset should be already in the catalog from a previous POST/PUT request
                    raise HTTPException(
                        detail=(f"The item that contains asset '{asset}' does not exist in the catalog "),
                        status_code=HTTP_400_BAD_REQUEST,
                    )
            else:
                # when alternate_key does not exist, it means the request is coming from the staging process,
                # and the s3_filename is on the temp bucket. this should be deleted later on after the catalog
                # insertion process is completed (see the use of clear_unnecessary_s3_files function)
                self.s3_keys_to_be_deleted.append(s3_filename)
            logger.debug(f"HTTP request add/update asset: {s3_filename!r}")
            fid = s3_filename.rsplit("/", maxsplit=1)[-1]
            if fid != asset:
                raise HTTPException(
                    detail=(
                        f"Invalid structure for the asset '{asset}'. The name of the key "
                        f"should be the filename, which is {fid} "
                    ),
                    status_code=HTTP_400_BAD_REQUEST,
                )
            # 2 - update alternate href to define catalog s3 bucket
            try:
                old_bucket_arr = s3_filename.split("/")
                old_bucket_arr[2] = CATALOG_BUCKET
                s3_key = "/".join(old_bucket_arr)
                # Check if the S3 key exists
                if not self.check_s3_key(item, asset, s3_key):
                    # update the 'href' key with the download link
                    new_href = f"https://{request.url.netloc}/catalog/\
collections/{user}:{collection_id}/items/{fid}/download/{asset}"
                    content["assets"][asset].update({"href": new_href})
                    # Update the S3 path to use the catalog bucket and create the alternate field
                    new_s3_href = {"s3": {"href": s3_key}}
                    content["assets"][asset].update({"alternate": new_s3_href})
                    # copy the key only if it isn't already on the final bucket
                    files_s3_key.append(s3_filename)
                elif request.method == "PUT":
                    # remove the asset from the item, all assets that remain shall
                    # be deleted from the s3 bucket later on
                    item["assets"].pop(asset)
            except (IndexError, AttributeError, KeyError) as exc:
                raise HTTPException(detail="Invalid obs bucket!", status_code=HTTP_400_BAD_REQUEST) from exc

        # 3 - include new stac extension if not present
        new_stac_extension = "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json"
        if new_stac_extension not in content["stac_extensions"]:
            content["stac_extensions"].append(new_stac_extension)

        # 4 - bucket handling
        self.s3_bucket_handling(files_s3_key, item, request)

        # 5 - add owner data
        content["properties"].update({"owner": user})
        content.update({"collection": f"{user}_{collection_id}"})
        return content

    def generate_presigned_url(self, content, path):
        """This function is used to generate a time-limited download url"""
        # Assume that pgstac already selected the correct asset id
        # just check type, generate and return url
        path_splitted = path.split("/")
        asset_id = path_splitted[-1]
        item_id = path_splitted[-3]
        try:
            s3_path = (
                content["assets"][asset_id]["alternate"]["s3"]["href"]
                .replace(
                    f"s3://{CATALOG_BUCKET}",
                    "",
                )
                .lstrip("/")
            )
        except KeyError:
            return f"Could not find asset named '{asset_id}' from item '{item_id}'", HTTP_404_NOT_FOUND
        try:
            s3_handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            )
            response = s3_handler.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": CATALOG_BUCKET, "Key": s3_path},
                ExpiresIn=PRESIGNED_URL_EXPIRATION_TIME,
            )
        except KeyError:
            return "Could not find s3 credentials", HTTP_400_BAD_REQUEST
        except botocore.exceptions.ClientError:
            return "Could not generate presigned url", HTTP_400_BAD_REQUEST
        return response, HTTP_302_FOUND

    def find_owner_id(self, ecql_ast: Node) -> str:
        """Browse an abstract syntax tree (AST) to find the owner_id.
        Then return it.

        Args:
            ecql_ast (_type_): The AST

        Returns:
            str: The owner_id
        """
        res = ""
        if hasattr(ecql_ast, "lhs"):
            if isinstance(ecql_ast.lhs, Attribute) and ecql_ast.lhs.name == "owner":
                if isinstance(ecql_ast, Like):
                    res = ecql_ast.pattern
                elif isinstance(ecql_ast, Equal):
                    res = ecql_ast.rhs
            elif left := self.find_owner_id(ecql_ast.lhs):
                res = left
            elif right := self.find_owner_id(ecql_ast.rhs):
                res = right
        return res

    async def collection_exists(self, request: Request, collection_id: str) -> bool:
        """Check if the collection exists.

        Returns:
            bool: True if the collection exists, False otherwise
        """
        try:
            await self.client.get_collection(collection_id, request)
            return True
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Collection %s not found: %s", collection_id, e)
            return False

    async def manage_search_request(  # pylint: disable=too-many-branches
        self,
        request: Request,
    ) -> Request | JSONResponse:
        """find the user in the filter parameter and add it to the
        collection name.

        Args:
            request Request: the client request.

        Returns:
            Request: the new request with the collection name updated.
        """
        auth_roles = []
        user_login = ""
        owner_id = ""
        collection_id = ""
        if common_settings.CLUSTER_MODE:  # Get the list of access and the user_login calling the endpoint.
            auth_roles = request.state.auth_roles
            user_login = request.state.user_login
        if request.method == "POST":  # POST method.
            content = await request.json()
            if (
                "filter-lang" not in content and "filter" in content
            ):  # If not specified, the default value of filter_lang in a post method is cql2-json.
                filter_lang = {"filter-lang": "cql2-json"}
                stac_filter = {}
                stac_filter["filter"] = content.pop("filter")
                content = {
                    **content,
                    **filter_lang,
                    **stac_filter,
                }  # The "filter_lang" field has to be placed BEFORE the filter.
            if self.request_ids["collection_id"]:  # /catalog/collections/{owner_id}:{collection_id}/search ENDPOINT.
                owner_id = (
                    user_login if not self.request_ids["owner_id"] else self.request_ids["owner_id"]
                )  # Implicit owner_id.
                collection_id = self.request_ids["collection_id"]
                if not owner_id:  # We don't have owner_id in local mode --> error.
                    detail = {"error": "Owner Id can't be implicit in local mode"}
                    return JSONResponse(content=detail, status_code=HTTP_401_UNAUTHORIZED)
                request = search_endpoint_in_collection_post(content, request, owner_id, collection_id)
            elif "filter" in content and "collections" in content:  # /catalo/search ENDPOINT.
                owner_id, collection_id, request = search_endpoint_post(content=content, request=request)
            if (
                not owner_id or not collection_id
            ):  # TODO find a solution to get authorisations in this case for next stories
                return request
        else:  # GET method.
            query = parse_qs(request.url.query)
            if self.request_ids["collection_id"]:  # /catalog/collections/{owner_id}:{collection_id}/search ENDPOINT.
                owner_id = (
                    user_login if not self.request_ids["owner_id"] else self.request_ids["owner_id"]
                )  # Implicit owner_id.
                collection_id = self.request_ids["collection_id"]
                request = search_endpoint_in_collection_get(query, request, owner_id, collection_id)
            elif "filter" in query and "collections" in query:  # /catalog/search ENDPOINT.
                owner_id, collection_id, request = search_endpoint_get(query=query, request=request)
            if (
                not owner_id or not collection_id
            ):  # TODO find a solution to get authorisations in this case for next stories
                return request
        if (  # If we are in cluster mode and the user_login is not authorized
            # to put/post returns a HTTP_401_UNAUTHORIZED status.
            common_settings.CLUSTER_MODE
            and not get_authorisation(
                collection_id,
                auth_roles,
                "read",
                owner_id,
                user_login,
            )
        ):
            detail = {"error": "Unauthorized access."}
            return JSONResponse(content=detail, status_code=HTTP_401_UNAUTHORIZED)
        if not await self.collection_exists(request, f"{owner_id}_{collection_id}"):
            detail = {"error": f"Collection {collection_id} not found."}
            return JSONResponse(content=detail, status_code=HTTP_404_NOT_FOUND)
        return request

    async def manage_search_response(self, request: Request, response: StreamingResponse) -> Response:
        """The '/catalog/search' endpoint doesn't give the information of the owner_id and collection_id.
        to get these values, this function try to search them into the search query. If successful,
        updates the response content by removing the owner_id from the collection_id and adapt all links.
        If not successful, does nothing and return the response.

        Args:
            response (StreamingResponse): The response from the rs server.
            request (Request): The request from the client.

        Returns:
            Response: The updated response.
        """
        filters: Optional[Node] = None
        owner_id, collection_id = "", ""
        if request.method == "GET":
            query = parse_qs(request.url.query)
            if "filter" in query:
                qs_filter = query["filter"][0]
                filters = parse_ecql(qs_filter)
        elif request.method == "POST":
            query = await request.json()
            if "filter" in query:
                qs_filter_json = query["filter"]
                filters = parse_cql2_json(qs_filter_json)
        owner_id = self.find_owner_id(filters)
        if "collections" in query:
            collection_id = query["collections"][0].removeprefix(owner_id)

        body = [chunk async for chunk in response.body_iterator]
        dec_content = b"".join(map(lambda x: x if isinstance(x, bytes) else x.encode(), body)).decode()  # type: ignore
        content = json.loads(dec_content)
        content = self.remove_user_from_objects(content, owner_id, "features")
        content = self.adapt_links(content, owner_id, collection_id, "features")

        # Add the stac authentication extension
        await self.add_authentication_extension(content)

        return JSONResponse(content, status_code=response.status_code)

    async def manage_put_post_request(  # pylint: disable=too-many-branches
        self,
        request: Request,
    ) -> Request | JSONResponse:
        """Adapt the request body for the STAC endpoint.

        Args:
            request (Request): The Client request to be updated.

        Returns:
            Request: The request updated.
        """
        user_login = ""
        auth_roles = []
        if common_settings.CLUSTER_MODE:  # Get the list of access and the user_login calling the endpoint.
            auth_roles = request.state.auth_roles
            user_login = request.state.user_login
        try:
            user = self.request_ids["owner_id"]
            content = await request.json()
            if (  # If we are in cluster mode and the user_login is not authorized
                # to put/post returns a HTTP_401_UNAUTHORIZED status.
                common_settings.CLUSTER_MODE
                and not get_authorisation(
                    self.request_ids["collection_id"],
                    auth_roles,
                    "write",
                    self.request_ids["owner_id"],
                    user_login,
                )
            ):
                detail = {"error": "Unauthorized access."}
                return JSONResponse(content=detail, status_code=HTTP_401_UNAUTHORIZED)

            if (
                request.scope["path"] == "/collections"  # POST collection
                or request.scope["path"] == f"/collections/{user}_{self.request_ids['collection_id']}"  # PUT collection
            ):
                # Manage a collection creation. The apikey user should be the same as the owner
                # field in the body request. In other words, an apikey user cannot create a
                # collection owned by another user.
                # We don't care for local mode, any user may create / delete collection owned by another user
                if common_settings.CLUSTER_MODE and user != user_login:
                    detail = {
                        "error": f"The '{user_login}' user cannot create a \
collection owned by the '{user}' user. Additionally, modifying the 'owner' field is not permitted also.",
                    }
                    logger.error(detail["error"])
                    return JSONResponse(content=detail, status_code=HTTP_401_UNAUTHORIZED)
                content["id"] = f"{user}_{content['id']}"
                if not content.get("owner"):
                    content["owner"] = user
                logger.debug(f"Handling for collection {content['id']}")
                # TODO update the links also?
            # The following section handles the request to create/update an item
            elif "items" in request.scope["path"]:
                # try to get the item if it is already part from the collection
                item = await self.get_item_from_collection(request)
                content = self.update_stac_item_publication(content, request, item)
                if content:
                    if request.method == "POST":
                        content = timestamps_extension.set_updated_expires_timestamp(content, "creation")
                        content = timestamps_extension.set_updated_expires_timestamp(content, "insertion")
                    else:  # PUT
                        published = expires = ""
                        if item and item.get("properties"):
                            published = item["properties"].get("published", "")
                            expires = item["properties"].get("expires", "")
                        if not published and not expires:
                            detail = {"error": f"Item {content['id']} not found."}
                            return JSONResponse(content=detail, status_code=HTTP_400_BAD_REQUEST)
                        content = timestamps_extension.set_updated_expires_timestamp(
                            content,
                            "update",
                            original_published=published,
                            original_expires=expires,
                        )
                if hasattr(content, "status_code"):
                    return content

            # update request body (better find the function that updates the body maybe?)c
            request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access

            return request  # pylint: disable=protected-access
        except KeyError as kerr_msg:
            raise HTTPException(
                detail=f"Missing key in request body! {kerr_msg}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from kerr_msg

    def manage_all_collections(self, collections: dict, auth_roles: list, user_login: str) -> list[dict]:
        """Return the list of all collections accessible by the user calling it.

        Args:
            collections (dict): List of all collections.
            auth_roles (list): List of roles of the api-key.
            user_login (str): The api-key owner.

        Returns:
            dict: The list of all collections accessible by the user.
        """
        catalog_read_right_pattern = (
            r"rs_catalog_(?P<owner_id>.*(?=:)):(?P<collection_id>.+)_(?P<right_type>read|write|download)(?=$)"
        )
        accessible_collections = []

        # Filter roles for read access
        read_roles = [role for role in auth_roles if re.match(catalog_read_right_pattern, role)]

        for role in read_roles:
            if match := re.match(catalog_read_right_pattern, role):
                groups = match.groupdict()
                if groups["right_type"] == "read":
                    owner_id = groups["owner_id"]
                    collection_id = groups["collection_id"]
                    accessible_collections.extend(
                        filter_collections(
                            collections,
                            owner_id if collection_id == "*" else f"{owner_id}_{collection_id}",
                        ),
                    )

        accessible_collections.extend(filter_collections(collections, user_login))
        return accessible_collections

    def get_collection_id(self, collection: dict[str, str], size_owner_id: int) -> str:
        """get the collection id with explicit typing

        Args:
            collection (dict[str, str]): The collection.
            size_owner_id (int): The size of owner id.

        Returns:
            str: the collection id.
        """
        return collection["id"][size_owner_id:]

    def update_links_for_all_collections(self, collections: list[dict]) -> list[dict]:
        """Update the links for the endpoint /catalog/collections.

        Args:
            collections (list[dict]): all the collections to be updated.

        Returns:
            list[dict]: all the collections after the links updated.
        """
        for collection in collections:
            owner_id = collection["owner"]
            size_owner_id = int(
                len(owner_id) + 1,
            )  # example: if collection['id']=='toto_S1_L1' then size_owner_id==len('toto_')==len('toto')+1.
            collection_id = self.get_collection_id(collection, size_owner_id)
            # example: if collection['id']=='toto_S1_L1' then collection_id=='S1_L1'.
            for link in collection["links"]:
                link_parser = urlparse(link["href"])
                new_path = add_user_prefix(link_parser.path, owner_id, collection_id)
                link["href"] = link_parser._replace(path=new_path).geturl()
        return collections

    def update_stac_catalog_metadata(self, metadata: dict):
        """Update the metadata fields from a catalog

        Args:
            metadata (dict): The metadata that has to be updated. The fields id, title,
                            description and stac_version are to be updated, by using the env vars which have
                            to be set before starting the app/pod. The existing values are used if
                            the env vars are not found
        """
        if metadata.get("type") == "Catalog":
            for key in ["id", "title", "description", "stac_version"]:
                if key in metadata:
                    metadata[key] = os.environ.get(f"CATALOG_METADATA_{key.upper()}", metadata[key])

    async def manage_get_response(  # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        self,
        request: Request,
        response: StreamingResponse,
    ) -> Response | JSONResponse:
        """Remove the user name from objects and adapt all links.

        Args:
            request (Request): The client request.
            response (Response | StreamingResponse): The response from the rs-catalog.
        Returns:
            Response: The response updated.
        """
        user = self.request_ids["owner_id"]
        body = [chunk async for chunk in response.body_iterator]
        dec_content = b"".join(map(lambda x: x if isinstance(x, bytes) else x.encode(), body)).decode()  # type: ignore
        content = json.loads(dec_content)
        self.update_stac_catalog_metadata(content)
        auth_roles = []
        user_login = ""

        if common_settings.CLUSTER_MODE:  # Get the list of access and the user_login calling the endpoint.
            auth_roles = request.state.auth_roles
            user_login = request.state.user_login
        if request.scope["path"] == "/":
            if common_settings.CLUSTER_MODE:  # /catalog
                content = manage_landing_page(auth_roles, user_login, content)
                if hasattr(content, "status_code"):  # Unauthorized
                    return content
            # Manage local landing page of the catalog
            regex_catalog = r"/collections/(?P<owner_id>.+?)_(?P<collection_id>.*)"
            for link in content["links"]:
                link_parser = urlparse(link["href"])

                if match := re.match(regex_catalog, link_parser.path):
                    groups = match.groupdict()
                    new_path = add_user_prefix(link_parser.path, groups["owner_id"], groups["collection_id"])
                    link["href"] = link_parser._replace(path=new_path).geturl()
            url = request.url._url  # pylint: disable=protected-access
            url = url[: len(url) - len(request.url.path)]
            content = add_prefix_link_landing_page(content, url)
        elif request.scope["path"] == "/collections":  # /catalog/owner_id/collections
            if user:
                content["collections"] = filter_collections(content["collections"], user)
                content = self.remove_user_from_objects(content, user, "collections")
                content = self.adapt_links(
                    content,
                    user,
                    self.request_ids["collection_id"],
                    "collections",
                )
            else:
                content["collections"] = self.manage_all_collections(
                    content["collections"],
                    auth_roles,
                    user_login,
                )
                content["collections"] = self.update_links_for_all_collections(content["collections"])
                self_parser = urlparse(content["links"][2]["href"])
                content["links"][0]["href"] += "catalog/"
                content["links"][1]["href"] += "catalog/"
                content["links"][2]["href"] = self_parser._replace(path="/catalog/collections").geturl()

        elif (  # If we are in cluster mode and the user_login is not authorized
            # to this endpoint returns a HTTP_401_UNAUTHORIZED status.
            common_settings.CLUSTER_MODE
            and self.request_ids["collection_id"]
            and self.request_ids["owner_id"]
            and not get_authorisation(
                self.request_ids["collection_id"],
                auth_roles,
                "read",
                self.request_ids["owner_id"],
                user_login,
            )
            # I don't know why but the STAC browser doesn't send authentication for the queryables endpoint.
            # So allow this endpoint without authentication in this specific case.
            and not (common_settings.request_from_stacbrowser(request) and request.url.path.endswith("/queryables"))
        ):
            detail = {"error": "Unauthorized access."}
            return JSONResponse(content=detail, status_code=HTTP_401_UNAUTHORIZED)
        elif (
            "/collections" in request.scope["path"] and "items" not in request.scope["path"]
        ):  # /catalog/collections/owner_id:collection_id
            content = remove_user_from_collection(content, user)
            content = self.adapt_object_links(content, user)
        elif (
            "items" in request.scope["path"] and not self.request_ids["item_id"]
        ):  # /catalog/owner_id/collections/collection_id/items
            content = self.remove_user_from_objects(content, user, "features")
            content = self.adapt_links(
                content,
                user,
                self.request_ids["collection_id"],
                "features",
            )
        elif request.scope["path"] == "/search":
            pass
        elif self.request_ids["item_id"]:  # /catalog/owner_id/collections/collection_id/items/item_id
            content = remove_user_from_feature(content, user)
            content = self.adapt_object_links(content, user)

        # Add the stac authentication extension
        await self.add_authentication_extension(content)

        return JSONResponse(content, status_code=response.status_code)

    async def manage_download_response(self, request: Request, response: StreamingResponse) -> Response:
        """
        Manage download response and handle requests that should generate a presigned URL.

        Args:
            request (starlette.requests.Request): The request object.
            response (starlette.responses.StreamingResponse): The response object received.

        Returns:
            JSONResponse: Returns a JSONResponse object containing either the presigned URL or
            the response content with the appropriate status code.

        """
        user_login = ""
        auth_roles = []
        if common_settings.CLUSTER_MODE:  # Get the list of access and the user_login calling the endpoint.
            auth_roles = request.state.auth_roles
            user_login = request.state.user_login
        if (  # If we are in cluster mode and the user_login is not authorized
            # to this endpoint returns a HTTP_401_UNAUTHORIZED status.
            common_settings.CLUSTER_MODE
            and self.request_ids["collection_id"]
            and self.request_ids["owner_id"]
            and not get_authorisation(
                self.request_ids["collection_id"],
                auth_roles,
                "download",
                self.request_ids["owner_id"],
                user_login,
            )
        ):
            detail = {"error": "Unauthorized access."}
            return JSONResponse(content=detail, status_code=HTTP_401_UNAUTHORIZED)
        body = [chunk async for chunk in response.body_iterator]
        content = json.loads(b"".join(body).decode())  # type:ignore
        if content.get("code", True) != "NotFoundError":
            # Only generate presigned url if the item is found
            content, code = self.generate_presigned_url(content, request.url.path)
            if code == HTTP_302_FOUND:
                return RedirectResponse(url=content, status_code=code)
            return JSONResponse(content, status_code=code)
        return JSONResponse(content, status_code=response.status_code)

    async def manage_put_post_response(self, request: Request, response: StreamingResponse):
        """
        Manage put or post responses.

        Args:
            response (starlette.responses.StreamingResponse): The response object received.

        Returns:
            JSONResponse: Returns a JSONResponse object containing the response content
            with the appropriate status code.

        Raises:
            HTTPException: If there is an error while clearing the temporary bucket,
            raises an HTTPException with a status code of 400 and detailed information.
            If there is a generic exception, raises an HTTPException with a status code
            of 400 and a generic bad request detail.

        """
        try:
            user = self.request_ids["owner_id"]
            body = [chunk async for chunk in response.body_iterator]
            response_content = json.loads(b"".join(body).decode())  # type: ignore
            if request.scope["path"] == "/collections":
                response_content = remove_user_from_collection(response_content, user)
                response_content = self.adapt_object_links(response_content, user)
            elif (
                request.scope["path"]
                == f"/collections/{user}_{self.request_ids['collection_id']}/items/{self.request_ids['item_id']}"
            ):
                response_content = remove_user_from_feature(response_content, user)
                response_content = self.adapt_object_links(response_content, user)
            self.clear_unnecessary_s3_files()
        except RuntimeError as exc:
            return JSONResponse(content=f"Failed to clean temporary bucket: {exc}", status_code=HTTP_400_BAD_REQUEST)
        except Exception as exc:  # pylint: disable=broad-except
            JSONResponse(content=f"Bad request: {exc}", status_code=HTTP_400_BAD_REQUEST)
        return JSONResponse(response_content, status_code=response.status_code)

    async def manage_delete_response(self, response: StreamingResponse, user: str) -> Response:
        """Change the name of the deleted collection by removing owner_id.

        Args:

            response (StreamingResponse): The client response.
            user (str): The owner id.

        Returns:
            JSONResponse: The new response with the updated collection name.
        """
        body = [chunk async for chunk in response.body_iterator]
        response_content = json.loads(b"".join(body).decode())  # type:ignore
        if "deleted collection" in response_content:
            response_content["deleted collection"] = response_content["deleted collection"].removeprefix(f"{user}_")
        return JSONResponse(response_content)

    def manage_delete_request(self, request: Request):
        """Check if the deletion is allowed.

        Args:
            request (Request): The client request.

        Raises:
            HTTPException: If the user is not authenticated.

        Returns:
            bool: Return True if the deletion is allowed, False otherwise.
        """
        user_login = getpass.getuser()
        auth_roles = []
        if common_settings.CLUSTER_MODE:  # Get the list of access and the user_login calling the endpoint.
            auth_roles = request.state.auth_roles
            user_login = request.state.user_login
        if (  # If we are in cluster mode and the user_login is not authorized
            # to this endpoint returns a HTTP_401_UNAUTHORIZED status.
            common_settings.CLUSTER_MODE
            and self.request_ids["collection_id"]
            and self.request_ids["owner_id"]
            and not get_authorisation(
                self.request_ids["collection_id"],
                auth_roles,
                "write",
                self.request_ids["owner_id"],
                user_login,
            )
        ):
            return False
        # we don't care for local mode, any user may create / delete collection owned by another user
        if common_settings.CLUSTER_MODE and self.request_ids["owner_id"] != user_login:
            # Manage a collection deletion. The apikey user (or local user if in local mode)
            # should be the same as the owner field in the body request. In other words, the
            # apikey user cannot delete a collection owned by another user
            logger.error(
                f"The '{user_login}' user cannot delete a \
collection or an item from a collection owned by the '{self.request_ids['owner_id']}' user",
            )
            return False
        return True

    async def retrieve_timestamp(self, request: Request) -> tuple[str, str]:
        """This function will retrieve the published and expires fields in the item
        we want to update to keep them unchanged.

        Args:
            request (Request): The initial request that is a put item.

        Returns:
            tuple[str, str]: published field, expires field.
        """

        try:
            item = await self.client.get_item(
                item_id=self.request_ids["item_id"],
                collection_id=f"{self.request_ids['owner_id']}_{self.request_ids['collection_id']}",
                request=request,
            )
            return (item["properties"]["published"], item["properties"]["expires"])
        except Exception:  # pylint: disable=broad-exception-caught
            return ("", "")

    async def dispatch(self, request, call_next):  # pylint: disable=too-many-branches, too-many-return-statements
        """Redirect the user catalog specific endpoint and adapt the response content."""
        request_body = None if request.method not in ["POST", "PUT"] else await request.json()
        # Get the the user_login calling the endpoint. If this is not set (the authentication.authenticate function
        # is not called), the local user shall be used (later on, in rereoute_url)
        # The common_settings.CLUSTER_MODE may not be used because for some endpoints like /api
        # the authenticate is not called even if common_settings.CLUSTER_MODE is True. Thus, the presence of
        # user_login has to be checked instead
        try:
            user_login = request.state.user_login
        except (NameError, AttributeError):
            # The current running user (if in local mode) will be used if needed in rerouting
            user_login = None
        logger.debug(
            f"Received {request.method} user_login is '{user_login}' url request.url.path = {request.url.path}",
        )
        request.scope["path"], self.request_ids = reroute_url(request.url.path, request.method, user_login)
        if not request.scope["path"]:  # Invalid endpoint
            return JSONResponse(content="Invalid endpoint.", status_code=HTTP_400_BAD_REQUEST)
        logger.debug(f"reroute_url formating: path = {request.scope['path']} | requests_ids = {self.request_ids}")
        # Overwrite user and collection id with the ones provided in the request body
        # This is available in POST/PUT/PATCH methods only
        if request_body:
            self.request_ids["owner_id"] = self.request_ids.get("owner_id") or request_body.get("owner")
            # received a POST/PUT/PATCH for a STAC item or
            # a STAC collection is created
            if not self.request_ids["collection_id"]:
                self.request_ids["collection_id"] = request_body.get("collection") or request_body.get("id")
            if not self.request_ids["item_id"] and request_body.get("type") == "Feature":
                self.request_ids["item_id"] = request_body.get("id", None)

        if "/health" in request.scope["path"]:
            # return true if up and running
            return JSONResponse(content="Healthy", status_code=HTTP_200_OK)
        # Handle requests
        if request.scope["path"] == "/search":
            # URL: GET: '/catalog/search'
            request = await self.manage_search_request(request)
            if hasattr(request, "status_code"):  # Unauthorized
                return request
        elif request.method in {"POST", "PUT"} and self.request_ids["owner_id"]:
            # URL: POST / PUT: '/catalog/collections/{USER}:{COLLECTION}'
            # or '/catalog/collections/{USER}:{COLLECTION}/items'
            request = await self.manage_put_post_request(request)
            if hasattr(request, "status_code"):  # Unauthorized
                return request
        elif request.method in ["POST", "PUT"] and not self.request_ids["owner_id"]:
            return JSONResponse(content="Invalid body.", status_code=HTTP_400_BAD_REQUEST)
        elif request.method == "DELETE":
            if not self.manage_delete_request(request):
                return JSONResponse(content="Deletion not allowed.", status_code=HTTP_401_UNAUTHORIZED)

        response = await call_next(request)

        # Don't forward responses that fail.
        # NOTE: the 30x (redirect responses) are used by the oauth2 authentication.
        if response.status_code not in (HTTP_200_OK, HTTP_201_CREATED, HTTP_302_FOUND, HTTP_307_TEMPORARY_REDIRECT):
            if response is None:
                return None

            # Read the body. WARNING: after this, the body cannot be read a second time.
            body = [chunk async for chunk in response.body_iterator]
            response_content = json.loads(b"".join(body).decode())  # type:ignore
            self.clear_catalog_bucket(response_content)

            # Return a regular JSON response instead of StreamingResponse because the body cannot be read again.
            return JSONResponse(status_code=response.status_code, content=response_content)

        # Handle responses
        if request.scope["path"] == "/search":
            # GET: '/catalog/search'
            response = await self.manage_search_response(request, response)
        elif request.method == "GET" and "download" in request.url.path:
            # URL: GET: '/catalog/collections/{USER}:{COLLECTION}/items/{FEATURE_ID}/download/{ASSET_TYPE}
            response = await self.manage_download_response(request, response)
        elif request.method == "GET" and (
            self.request_ids["owner_id"] or request.scope["path"] in ["/", "/collections", "/queryables"]
        ):
            # URL: GET: '/catalog/collections/{USER}:{COLLECTION}'
            # URL: GET: '/catalog/'
            # URL: GET: '/catalog/collections
            response = await self.manage_get_response(request, response)
        elif request.method in ["POST", "PUT"] and self.request_ids["owner_id"]:
            # URL: POST / PUT: '/catalog/collections/{USER}:{COLLECTION}'
            # or '/catalog/collections/{USER}:{COLLECTION}/items'
            response = await self.manage_put_post_response(request, response)
        elif request.method == "DELETE" and self.request_ids["owner_id"]:
            response = await self.manage_delete_response(response, self.request_ids["owner_id"])

        return response

    async def add_authentication_extension(self, content: dict):
        """Add the stac authentication extension, see: https://github.com/stac-extensions/authentication"""

        # Only on cluster mode
        if not common_settings.CLUSTER_MODE:
            return

        # Read environment variables
        oidc_endpoint = os.environ["OIDC_ENDPOINT"]
        oidc_realm = os.environ["OIDC_REALM"]
        oidc_metadata_url = f"{oidc_endpoint}/realms/{oidc_realm}/.well-known/openid-configuration"

        # Add the STAC extension at the root
        extensions = content.setdefault("stac_extensions", [])
        url = "https://stac-extensions.github.io/authentication/v1.1.0/schema.json"
        if url not in extensions:
            extensions.append(url)

        # Add the authentication schemes under the root or "properties" (for the items)
        parent = content
        if content.get("type") == "Feature":
            parent = content.setdefault("properties", {})
        oidc = await oauth2.KEYCLOAK.load_server_metadata()
        parent.setdefault("auth:schemes", {}).update(
            {
                "apikey": {
                    "type": "apiKey",
                    "description": f"API key generated using {os.environ['RSPY_UAC_HOMEPAGE']}"  # link to /docs
                    # add anchor to the "new api key" endpoint
                    "#/Manage%20API%20keys/get_new_api_key_auth_api_key_new_get",
                    "name": "x-api-key",
                    "in": "header",
                },
                "openid": {
                    "type": "openIdConnect",
                    "description": "OpenID Connect",
                    "openIdConnectUrl": oidc_metadata_url,
                },
                "oauth2": {
                    "type": "oauth2",
                    "description": "OAuth2+PKCE Authorization Code Flow",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": oidc["authorization_endpoint"],
                            "tokenUrl": oidc["token_endpoint"],
                            "scopes": {},
                        },
                    },
                },
            },
        )

        # Add the authentication reference to each link and asset
        for link_or_asset in content.get("links", []) + list(content.get("assets", {}).values()):
            link_or_asset["auth:refs"] = ["apikey", "openid", "oauth2"]
        # Add the extension to the response root and to nested collections, items, ...
        # Do recursive calls to all nested fields, if defined
        for nested_field in ["collections", "features"]:
            for nested_content in content.get(nested_field, []):
                await self.add_authentication_extension(nested_content)
