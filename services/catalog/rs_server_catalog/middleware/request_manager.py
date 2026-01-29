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

"""Module to process the Requests sent by users to the Catalog before routing them to stac-fastapi."""

import asyncio
import copy
import getpass
import json
from functools import lru_cache
from typing import Any, cast
from urllib.parse import urlencode

from fastapi import HTTPException
from rs_server_catalog.authentication_catalog import (
    check_user_authorization,
    get_authorisation,
)
from rs_server_catalog.data_management import timestamps_extension
from rs_server_catalog.data_management.s3_manager import S3Manager
from rs_server_catalog.data_management.user_handler import (
    CATALOG_COLLECTIONS,
    get_user,
    owner_id_and_collection_id,
)
from rs_server_catalog.utils import (
    DEFAULT_BBOX,
    DEFAULT_GEOM,
    extract_owner_name_from_json_filter,
    extract_owner_name_from_text_filter,
    get_token_for_pagination,
)
from rs_server_common import settings as common_settings
from rs_server_common.utils.cql2_filter_extension import process_filter_extensions
from rs_server_common.utils.logging import Logging
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.types.errors import NotFoundError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
)

logger = Logging.default(__name__)


class CatalogRequestManager:
    """Class to process the Requests sent by users to the Catalog before routing them to stac-fastapi.
    Each type of Response is managed in one of the functions."""

    def __init__(self, client: CoreCrudClient, request_ids: dict[Any, Any]):
        self.client = client
        self.request_ids = request_ids
        self.s3_files_to_be_deleted: list = []

    @lru_cache
    def s3_manager(self):
        """Creates a cached instance of S3Manager for this class instance (self)."""
        return S3Manager()

    def _override_request_body(self, request: Request, content: Any) -> Request:
        """Update request body (better find the function that updates the body maybe?)"""
        request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access
        request._json = content  # pylint: disable=protected-access
        logger.debug("new request body and json: %s", request._body)  # pylint: disable=protected-access
        return request

    def _override_request_query_string(self, request: Request, query_params: dict) -> Request:
        """Update request query string"""
        request.scope["query_string"] = urlencode(query_params, doseq=True).encode("utf-8")
        logger.debug("new request query_string: %s", request.scope["query_string"])
        return request

    async def _collection_exists(self, request: Request, collection_id: str) -> bool:
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

    async def _get_item_from_collection(self, request: Request):
        """Get an item from the collection.

        Args:
            request (Request): The request object.

        Returns:
            Optional[Dict]: The item from the collection if found, else None.
        """
        item_id = self.request_ids["item_id"]
        collection_id = f"{self.request_ids['owner_id']}_{self.request_ids['collection_ids'][0]}"
        try:
            item = await self.client.get_item(item_id=item_id, collection_id=collection_id, request=request)
            return item
        except NotFoundError:
            logger.info(f"The item '{item_id}' does not exist in collection '{collection_id}'")
            return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception(f"Exception: {e}")
            raise HTTPException(
                detail=f"Exception when trying to get the item {item_id} from the collection '{collection_id}'",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    async def build_filelist_to_be_deleted(self, request):
        """Build the list of the s3 files that will be deleted if the request is successfull"""
        for ci in self.request_ids["collection_ids"]:
            collection_id = f"{self.request_ids['owner_id']}_{ci}"
            items = []
            try:
                if "/items" not in request.scope["path"]:
                    # this is the case for delete endpoint /collections/<collection_name>
                    # use pagination, otherwise a maximum of the default limit (10) items is returned
                    # NOTE: Unable to use the pagination from pgstac client. Temporary, use a limit of 100
                    token = None
                    while True:
                        items_collection = await self.client.item_collection(
                            request=request,
                            collection_id=collection_id,
                            limit=100,
                            token=token,
                        )
                        items.extend(items_collection.get("features", []))
                        # Check if there's a next token for pagination
                        token = get_token_for_pagination(items_collection)

                        if not token:
                            # No more pages left, break the loop
                            break
                else:
                    # this is the case for delete endpoint /collections/<collection_name>/items/<item_name>
                    item = await self.client.get_item(
                        item_id=self.request_ids["item_id"],
                        collection_id=collection_id,
                        request=request,
                    )
                    items = [item]
            except NotFoundError as nfe:
                logger.error(f"Failed to find the requested object to be deleted. {nfe}")
                return
            except KeyError as e:
                logger.error(f"Failed to build the list of items to be deleted due to missing key: {e}")
                return
            logger.debug(f"Found {len(items)} items: {items}")
            try:
                for item in items:
                    assets = item.get("assets", {})
                    for _, asset_info in assets.items():
                        s3_href = asset_info.get("href")
                        if s3_href:
                            self.s3_files_to_be_deleted.append(s3_href)
            except KeyError as e:
                logger.error(
                    f"Failed to build the list of S3 files to be deleted due to missing key in dictionary: {e}",
                )
                return
            logger.info(
                "Successfully built the list of S3 files to be deleted. "
                f"There are {len(self.s3_files_to_be_deleted)} files to be deleted",
            )

    async def manage_requests(self, request: Request) -> Request | Response:
        """Main function to dispatch the request pre-processing depending on which endpoint is called.
        Will pre-process the request using the function associated to the path called and return it.

        Args:
            request (Request): request received by the Catalog.

        Returns:
            Request|Response: Request processed to be sent to stac-fastapi OR a response if the operation
                is not authorized
        """
        if request.method in ("POST", "PUT") and "/search" not in request.scope["path"]:
            # URL: POST / PUT: '/catalog/collections/{USER}:{COLLECTION}'
            # or '/catalog/collections/{USER}:{COLLECTION}/items'
            request_or_response = await self.manage_put_post_request(request)
            if hasattr(request_or_response, "status_code"):  # Unauthorized
                return cast(Response, request_or_response)
            request = request_or_response

        elif request.method == "DELETE":
            if not await self.manage_delete_request(request):
                raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Deletion not allowed.")

        elif "/search" in request.scope["path"]:
            # URL: GET: '/catalog/search'
            request_or_response = await self.manage_search_request(request)
            if hasattr(request_or_response, "status_code"):  # Unauthorized
                return cast(Response, request_or_response)
            request = request_or_response

        elif request.method == "GET" and request.scope["path"] == CATALOG_COLLECTIONS:
            # override default pgstac limit of 10 items if not explicitely set
            if "limit" not in request.query_params:
                request = self._override_request_query_string(request, {**request.query_params, "limit": 1000})

        elif request.method == "PATCH":
            request_or_response = await self.manage_patch_request(request)
            if hasattr(request_or_response, "status_code"):  # Unauthorized
                return cast(Response, request_or_response)
            request = request_or_response

        return request

    async def manage_put_post_request(  # pylint: disable=too-many-statements,too-many-return-statements,too-many-branches  # noqa: E501
        self,
        request: Request,
    ) -> Request | JSONResponse:
        """Adapt the request body for the STAC endpoint.

        Args:
            request (Request): The Client request to be updated.

        Returns:
            Request: The request updated.
        """
        try:
            original_content = await request.json()
            content = copy.deepcopy(original_content)

            check_user_authorization(self.request_ids)

            if len(self.request_ids["collection_ids"]) > 1:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail="Cannot create or update more than one collection !",
                )

            if len(self.request_ids["collection_ids"]) == 0:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail="Cannot create or update -> no collection specified !",
                )

            collection = self.request_ids["collection_ids"][0]
            if (
                # POST collection
                request.scope["path"]
                == CATALOG_COLLECTIONS
            ) or (
                # PUT collection
                request.scope["path"]
                == f"{CATALOG_COLLECTIONS}/{self.request_ids['owner_id']}_{collection}"
            ):
                # Manage a collection creation. The apikey user should be the same as the owner
                # field in the body request. In other words, an apikey user cannot create a
                # collection owned by another user.
                # We don't care for local mode, any user may create / delete collection owned by another user
                if common_settings.CLUSTER_MODE and (self.request_ids["owner_id"] != self.request_ids["user_login"]):
                    error = f"The '{self.request_ids['user_login']}' user cannot create a \
collection owned by the '{self.request_ids['owner_id']}' user. Additionally, modifying the 'owner' \
field is not permitted also."
                    raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail=error)

                content["id"] = owner_id_and_collection_id(self.request_ids["owner_id"], content["id"])
                if not content.get("owner"):
                    content["owner"] = self.request_ids["owner_id"]

                # See if there is already a collection with this ID. If yes, retrieve its "created" value.
                try:
                    existing_collection = await self.client.get_collection(content["id"], request)
                    date_of_creation = existing_collection.get("created", "")
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.debug("Collection %s doesn't exist and will be created: %s", content["id"], e)
                    date_of_creation = ""

                # Update timestamps ("updated", and "created" if it's a new collection)
                content = timestamps_extension.set_timestamps_to_collection(content, original_created=date_of_creation)
                logger.debug(f"Handling for collection {content['id']}")
                # TODO update the links also?

            # The following section handles the request to create/update an item
            elif "/items" in request.scope["path"]:
                # first check if the collection exists
                if not await self._collection_exists(request, f"{self.request_ids['owner_id']}_{collection}"):
                    raise HTTPException(
                        status_code=HTTP_404_NOT_FOUND,
                        detail=f"Collection {collection} does not exist.",
                    )

                # try to get the item if it is already part from the collection
                item = await self._get_item_from_collection(request)
                logger.debug("Starting the update_stac_item_publication thread")
                content, self.s3_files_to_be_deleted = await asyncio.to_thread(
                    self.s3_manager().update_stac_item_publication,
                    content,
                    request,
                    self.request_ids,
                    item,
                )
                logger.debug("The update_stac_item_publication thread finished")
                if content:
                    if request.method == "POST":
                        content = timestamps_extension.set_timestamps_for_creation(content)
                        content = timestamps_extension.set_timestamps_for_insertion(content)
                    else:  # PUT
                        published = expires = ""
                        if item and item.get("properties"):
                            published = item["properties"].get("published", "")
                            expires = item["properties"].get("expires", "")
                        if not published and not expires:
                            raise HTTPException(
                                status_code=HTTP_400_BAD_REQUEST,
                                detail=f"Item {content['id']} not found.",
                            )
                        content = timestamps_extension.set_timestamps_for_update(
                            content,
                            original_published=published,
                            original_expires=expires,
                        )
                    # If item doesn't contain a geometry/bbox, just fill with a default one.
                    if not content.get("geometry", None):
                        content["geometry"] = DEFAULT_GEOM
                    if not content.get("bbox", None):
                        content["bbox"] = DEFAULT_BBOX
                if hasattr(content, "status_code"):
                    return content

            # update request body if needed
            if content != original_content:
                request = self._override_request_body(request, content)

            logger.debug(f"Sending back the response for {request.method} {request.scope['path']}")
            return request  # pylint: disable=protected-access
        except KeyError as kerr_msg:
            raise HTTPException(
                detail=f"Missing key in request body! {kerr_msg}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from kerr_msg

    async def manage_delete_request(self, request: Request):
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
            and self.request_ids["collection_ids"]
            and self.request_ids["owner_id"]
            and not get_authorisation(
                self.request_ids["collection_ids"],
                auth_roles,
                "write",
                self.request_ids["owner_id"],
                user_login,
            )
        ):
            return False

        # Manage a collection deletion. The apikey user (or local user if in local mode)
        # should be the same as the owner field in the body request. In other words, the
        # apikey user cannot delete a collection owned by another user
        # we don't care for local mode, any user may create / delete collection owned by another user
        if (
            (  # DELETE collection
                request.scope["path"]
                == f"{CATALOG_COLLECTIONS}/{self.request_ids['owner_id']}_{self.request_ids['collection_ids'][0]}"
            )
            and common_settings.CLUSTER_MODE
            and (self.request_ids["owner_id"] != user_login)
        ):
            logger.error(
                f"The '{user_login}' user cannot delete a \
collection owned by the '{self.request_ids['owner_id']}' user",
            )
            return False

        await self.build_filelist_to_be_deleted(request)
        return True

    async def manage_search_request(  # pylint: disable=too-many-statements,too-many-branches
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
        # ---------- POST requests
        if request.method == "POST":
            content = await request.json()

            # Pre-processing of filter extensions
            if "filter" in content:
                content["filter"] = process_filter_extensions(content["filter"])

            # Management of priority for the assignation of the owner_id
            if not self.request_ids["owner_id"]:
                self.request_ids["owner_id"] = (
                    (extract_owner_name_from_json_filter(content["filter"]) if "filter" in content else None)
                    or content.get("owner")
                    or get_user(self.request_ids["owner_id"], self.request_ids["user_login"])
                )

            # Add filter-lang option to the content if it doesn't already exist
            if "filter" in content:
                filter_lang = {"filter-lang": content.get("filter-lang", "cql2-json")}
                stac_filter = content.pop("filter")
                content = {
                    **content,
                    **filter_lang,
                    "filter": stac_filter,
                }  # The "filter_lang" field has to be placed BEFORE the filter.

            # ----- Call /catalog/search with POST method endpoint
            if "collections" in content:
                # Check if each collection exist with their raw name, if not concatenate owner_id to the collection name
                for i, collection in enumerate(content["collections"]):
                    if not await self._collection_exists(request, collection):
                        content["collections"][i] = f"{self.request_ids['owner_id']}_{collection}"
                        logger.debug(f"Using collection name: {content['collections'][i]}")
                        # Check the existence of the collection after concatenation of owner_id
                        if not await self._collection_exists(request, content["collections"][i]):
                            raise HTTPException(
                                status_code=HTTP_404_NOT_FOUND,
                                detail=f"Collection {collection} not found.",
                            )

                self.request_ids["collection_ids"] = content["collections"]
                request = self._override_request_body(request, content)

        # ---------- GET requests
        elif request.method == "GET":
            # Get dictionary of query parameters
            query_params_dict = dict(request.query_params)

            # Update owner_id if it is not already defined from path parameters
            if not self.request_ids["owner_id"]:
                self.request_ids["owner_id"] = (
                    (
                        extract_owner_name_from_text_filter(query_params_dict["filter"])
                        if "filter" in query_params_dict
                        else ""
                    )
                    or query_params_dict.get("owner")
                    or get_user(self.request_ids["owner_id"], self.request_ids["user_login"])
                )

            # ----- Catch endpoint catalog/search + query parameters (e.g. /search?ids=S3_OLC&collections=titi)
            if "collections" in query_params_dict:
                coll_list = query_params_dict["collections"].split(",")

                # Check if each collection exist with their raw name, if not concatenate owner_id to the collection name
                for i, collection in enumerate(coll_list):
                    if not await self._collection_exists(request, collection):
                        coll_list[i] = f"{self.request_ids['owner_id']}_{collection}"
                        logger.debug(f"Using collection name: {coll_list[i]}")
                        # Check the existence of the collection after concatenation of owner_id
                        if not await self._collection_exists(request, coll_list[i]):
                            raise HTTPException(
                                status_code=HTTP_404_NOT_FOUND,
                                detail=f"Collection {collection} not found.",
                            )

                self.request_ids["collection_ids"] = coll_list
                query_params_dict["collections"] = ",".join(coll_list)
                request = self._override_request_query_string(request, query_params_dict)

        # Check that the collection from the request exists
        for collection in self.request_ids["collection_ids"]:
            if not await self._collection_exists(request, collection):
                raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Collection {collection} not found.")

        # Check authorisation in cluster mode
        if common_settings.CLUSTER_MODE:
            get_authorisation(
                self.request_ids["collection_ids"],
                self.request_ids["auth_roles"],
                "read",
                self.request_ids["owner_id"],
                self.request_ids["user_login"],
                # When calling the /search endpoints, the catalog ids are always prefixed by their <owner>_
                owner_prefix=True,
                raise_if_unauthorized=True,
            )
        return request

    async def manage_patch_request(self, request: Request):
        """
        Pre-processing of a PATCH request to the Catalog.
        Does authorization checks and updates the "updated" field of the item to patch.

        Args:
            request (Request): The request from the Client

        Returns:
            Request: Updated request
        """
        try:
            original_content = await request.json()
            content = copy.deepcopy(original_content)

            check_user_authorization(self.request_ids)

            # Update "updated" timestamp (different field if it is an item or a collection)
            is_item = "/items/" in request.scope["path"]
            content = timestamps_extension.set_updated_timestamp_to_now(content, is_item=is_item)

            request = self._override_request_body(request, content)
            return request

        except KeyError as kerr_msg:
            raise HTTPException(
                detail=f"Missing key in request body! {kerr_msg}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from kerr_msg
