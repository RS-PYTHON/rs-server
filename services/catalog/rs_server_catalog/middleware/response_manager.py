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

"""Module to process the Responses returned by stac-fastapi for the Catalog middleware."""

import asyncio
import re
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from fastapi import HTTPException
from rs_server_catalog.authentication_catalog import (
    get_all_accessible_collections,
    get_authorisation,
)
from rs_server_catalog.data_management.s3_manager import S3Manager
from rs_server_catalog.data_management.stac_manager import StacManager
from rs_server_catalog.data_management.user_handler import (
    CATALOG_COLLECTIONS,
    adapt_links,
    adapt_object_links,
    add_user_prefix,
)
from rs_server_catalog.utils import (
    CATALOG_PREFIX,
    DEFAULT_BBOX,
    DEFAULT_GEOM,
    add_prefix_link_landing_page,
    extract_owner_name_from_json_filter,
    extract_owner_name_from_text_filter,
    headers_minus_content_length,
)
from rs_server_common import settings as common_settings
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import read_streaming_response
from stac_fastapi.api.models import GeoJSONResponse
from stac_fastapi.pgstac.core import CoreCrudClient
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
)

QUERYABLES = "/queryables"

logger = Logging.default(__name__)


class CatalogResponseManager:
    """Class to process the Responses returned by stac-fastapi for the Catalog middleware.
    Each type of Response is managed in one of the functions."""

    def __init__(
        self,
        client: CoreCrudClient,
        request_ids: dict[Any, Any],
        s3_files_to_be_deleted: list[str] | None = None,
    ):
        self.client = client
        self.request_ids = request_ids
        self.s3_files_to_be_deleted = s3_files_to_be_deleted or []

    @lru_cache
    def s3_manager(self):
        """Creates a cached instance of S3Manager for this class instance (self)."""
        return S3Manager()

    async def manage_responses(
        self,
        request: Request,
        streaming_response: StreamingResponse,
    ) -> Response:
        """Manage responses sent by stac-fastpi after dispatch and before sending it to the user.

        Args:
            request (Request): Original request sent to stac-fastapi
            streaming_response (StreamingResponse): Response returned by stac-fastapi

        Returns:
            Response: HTTP Response
        """

        # Don't forward responses that fail.
        # NOTE: the 30x (redirect responses) are used by the oauth2 authentication.
        status_code = streaming_response.status_code
        if status_code not in (HTTP_200_OK, HTTP_201_CREATED, HTTP_302_FOUND, HTTP_307_TEMPORARY_REDIRECT):

            # Read the body
            response_content = await read_streaming_response(streaming_response)
            logger.debug("response: %d - %s", streaming_response.status_code, response_content)
            await asyncio.to_thread(self.s3_manager().clear_catalog_bucket, response_content)

            # GET: '/catalog/queryables' when no collections in the catalog
            if (
                request.method == "GET"
                and request.scope["path"] == CATALOG_PREFIX + QUERYABLES
                and not self.request_ids["collection_ids"]
                and response_content["code"] == "NotFoundError"
            ):
                # Return empty list of properties and additionalProperties set to true on /catalog/queryables
                # when there are no collections in catalog.
                return JSONResponse(
                    {
                        "$id": f"{request.url}",
                        "type": "object",
                        "title": "STAC Queryables.",
                        "$schema": "https://json-schema.org/draft-07/schema#",
                        "properties": {},
                        "additionalProperties": True,
                    },
                    HTTP_200_OK,
                    headers_minus_content_length(streaming_response),
                )

            # Return a regular JSON response instead of StreamingResponse because the body cannot be read again.
            return JSONResponse(response_content, status_code, headers_minus_content_length(streaming_response))

        # Handle responses
        response: Response = streaming_response
        if request.scope["path"] == CATALOG_PREFIX + "/search":
            # GET: '/catalog/search'
            response = await self.manage_search_response(request, streaming_response)
        elif request.method == "GET" and "/download" in request.url.path:
            # URL: GET: '/catalog/collections/{USER}:{COLLECTION}/items/{FEATURE_ID}/download/{ASSET_TYPE}
            response = await self.manage_download_response(request, streaming_response)
        elif request.method == "GET" and (
            self.request_ids["owner_id"]
            or request.scope["path"] in [CATALOG_PREFIX, CATALOG_PREFIX + "/", CATALOG_COLLECTIONS, QUERYABLES]
        ):
            # URL: GET: '/catalog/collections/{USER}:{COLLECTION}'
            # URL: GET: '/catalog/'
            # URL: GET: '/catalog/collections
            response = await self.manage_get_response(request, streaming_response)
        elif request.method in ["POST", "PUT"] and self.request_ids["owner_id"]:
            # URL: POST / PUT: '/catalog/collections/{USER}:{COLLECTION}'
            # or '/catalog/collections/{USER}:{COLLECTION}/items'
            response = await self.manage_put_post_response(request, streaming_response)
        elif request.method == "DELETE" and self.request_ids["owner_id"]:
            response = await self.manage_delete_response(streaming_response, self.request_ids["owner_id"])

        return response

    async def manage_search_response(self, request: Request, response: StreamingResponse) -> GeoJSONResponse:
        """The '/catalog/search' endpoint doesn't give the information of the owner_id and collection_ids.
        to get these values, this function try to search them into the search query. If successful,
        updates the response content by removing the owner_id from the collection_ids and adapt all links.
        If not successful, does nothing and return the response.

        Args:
            response (StreamingResponse): The response from the rs server.
            request (Request): The request from the client.

        Returns:
            GeoJSONResponse: The updated response.
        """
        owner_id = ""
        if request.method == "GET":
            query = parse_qs(request.url.query)
            if "filter" in query:
                qs_filter = query["filter"][0]
                owner_id = extract_owner_name_from_text_filter(qs_filter)
        elif request.method == "POST":
            query = await request.json()
            if "filter" in query:
                qs_filter_json = query["filter"]
                owner_id = extract_owner_name_from_json_filter(qs_filter_json)

        if owner_id:
            self.request_ids["owner_id"] = owner_id

        # Remove owner_id from the collection name
        if "collections" in query:
            # Extract owner_id from the name of the first collection in the list
            self.request_ids["owner_id"] = self.request_ids["collection_ids"][0].split("_")[0]
            self.request_ids["collection_ids"] = [
                coll.removeprefix(f"{self.request_ids['owner_id']}_") for coll in query["collections"][0].split(",")
            ]
        content = await read_streaming_response(response)
        content = adapt_links(content, "features")
        for collection_id in self.request_ids["collection_ids"]:
            content = adapt_links(content, "features", self.request_ids["owner_id"], collection_id)

        # Add the stac authentication extension
        await StacManager.add_authentication_extension(content)

        return GeoJSONResponse(content, response.status_code, headers_minus_content_length(response))

    async def manage_download_response(
        self,
        request: Request,
        response: StreamingResponse,
    ) -> JSONResponse | RedirectResponse:
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
            # to this endpoint raise a HTTP_401_UNAUTHORIZED status.
            common_settings.CLUSTER_MODE
            and self.request_ids["collection_ids"]
            and self.request_ids["owner_id"]
        ):
            get_authorisation(
                self.request_ids["collection_ids"],
                auth_roles,
                "download",
                self.request_ids["owner_id"],
                user_login,
                raise_if_unauthorized=True,
            )
        content = await read_streaming_response(response)
        if content.get("code", True) != "NotFoundError":
            # Only generate presigned url if the item is found
            content, code = await asyncio.to_thread(self.s3_manager().generate_presigned_url, content, request.url.path)
            if code == HTTP_302_FOUND:
                return RedirectResponse(url=content, status_code=code)
            return JSONResponse(content, code, headers_minus_content_length(response))
        return JSONResponse(content, response.status_code, headers_minus_content_length(response))

    async def manage_get_response(
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
        # Load content of the response as a dictionary
        dec_content = await read_streaming_response(response)
        content = await self._manage_get_response_content(request, dec_content) if dec_content else None
        media_type = "application/geo+json" if "/items" in request.scope["path"] else None
        return JSONResponse(content, response.status_code, headers_minus_content_length(response), media_type)

    async def _manage_get_response_content(  # pylint: disable=too-many-locals, too-many-branches, too-many-statements
        self,
        request: Request,
        content: Any,
    ) -> Any:
        """Manage content of GET responses with a body

        Args:
            request (Request): The client request.
            dec_content (str): The decoded json content
        Returns:
            Any: the response content
        """
        StacManager.update_stac_catalog_metadata(content)
        auth_roles = []
        user_login = ""

        if content.get("geometry") == DEFAULT_GEOM:
            content["geometry"] = None
        if content.get("bbox") == DEFAULT_BBOX:
            content["bbox"] = None

        if common_settings.CLUSTER_MODE:  # Get the list of access and the user_login calling the endpoint.
            auth_roles = request.state.auth_roles
            user_login = request.state.user_login

        # Manage local landing page of the catalog
        if request.scope["path"] in (CATALOG_PREFIX, CATALOG_PREFIX + "/"):
            regex_catalog = CATALOG_COLLECTIONS + r"/(?P<owner_id>.+?)_(?P<collection_id>.*)"
            for link in content["links"]:
                link_parser = urlparse(link["href"])

                if match := re.match(regex_catalog, link_parser.path):
                    groups = match.groupdict()
                    new_path = add_user_prefix(link_parser.path, groups["owner_id"], groups["collection_id"])
                    link["href"] = link_parser._replace(path=new_path).geturl()
            url = request.url._url  # pylint: disable=protected-access
            url = url[: len(url) - len(request.url.path)]
            content = add_prefix_link_landing_page(content, url)

            # patch the catalog landing page with "rel": "child" link for each collection
            # limit must be explicitely set, otherwise the default pgstac limit of 10 is used
            collections_resp = await self.client.all_collections(request=request, limit=1000)
            collections = get_all_accessible_collections(
                collections_resp.get("collections", []),
                auth_roles,
                user_login,
            )
            base_url = (
                next((link["href"] for link in content["links"] if link.get("rel") == "self"), "").rstrip("/") + "/"
            )

            for collection in collections:
                collection_id = (
                    collection["id"].removeprefix(f"{collection['owner']}_")
                    if collection["owner"]
                    else collection["id"]
                )
                content["links"].append(
                    {
                        "rel": "child",
                        "type": "application/json",
                        "title": collection.get("title") or collection_id,
                        "href": urljoin(base_url, f"collections/{collection['owner']}:{collection_id}"),
                    },
                )

        elif request.scope["path"] == CATALOG_COLLECTIONS:  # /catalog/collections
            content["collections"] = get_all_accessible_collections(
                content["collections"],
                auth_roles,
                user_login,
            )
            content["collections"] = StacManager.update_links_for_all_collections(content["collections"])

        # If we are in cluster mode and the user_login is not authorized
        # to this endpoint raise a HTTP_401_UNAUTHORIZED status.
        elif (
            common_settings.CLUSTER_MODE
            and self.request_ids["collection_ids"]
            and self.request_ids["owner_id"]
            and not get_authorisation(
                self.request_ids["collection_ids"],
                auth_roles,
                "read",
                self.request_ids["owner_id"],
                user_login,
                raise_if_unauthorized=True,
            )
        ):
            pass  # an exception was raised by get_authorisation in this case
        elif (
            "/collections" in request.scope["path"] and "/items" not in request.scope["path"]
        ):  # /catalog/collections/owner_id:collection_id
            content = adapt_object_links(content, self.request_ids["owner_id"])
        elif (
            "/items" in request.scope["path"] and not self.request_ids["item_id"]
        ):  # /catalog/owner_id/collections/collection_id/items
            content = adapt_links(
                content,
                "features",
                self.request_ids["owner_id"],
                self.request_ids["collection_ids"][0],
            )
        elif self.request_ids["item_id"]:  # /catalog/owner_id/collections/collection_id/items/item_id
            content = adapt_object_links(content, self.request_ids["owner_id"])
        else:
            logger.debug(f"No link adaptation performed for {request.scope}")

        # Add the stac authentication extension
        await StacManager.add_authentication_extension(content)
        return content

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
            response_content = await read_streaming_response(response)
            response_content = adapt_object_links(response_content, self.request_ids["owner_id"])

            # Don't display geometry and bbox for default case since it was added just for compliance.
            if request.scope["path"].startswith(
                f"{CATALOG_COLLECTIONS}/{user}_{self.request_ids['collection_ids'][0]}/items",
            ):
                if response_content.get("geometry") == DEFAULT_GEOM:
                    response_content["geometry"] = None
                if response_content.get("bbox") == DEFAULT_BBOX:
                    response_content["bbox"] = None
            await self.s3_manager().delete_s3_files(self.s3_files_to_be_deleted)
            self.s3_files_to_be_deleted.clear()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=f"Failed to clean temporary bucket: {exc}",
            ) from exc
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"Bad request: {exc}") from exc
        media_type = "application/geo+json" if "/items" in request.scope["path"] else None
        return JSONResponse(response_content, response.status_code, headers_minus_content_length(response), media_type)

    async def manage_delete_response(self, response: StreamingResponse, user: str) -> Response:
        """Change the name of the deleted collection by removing owner_id.

        Args:
            response (StreamingResponse): The client response.
            user (str): The owner id.

        Returns:
            JSONResponse: The new response with the updated collection name.
        """
        response_content = await read_streaming_response(response)
        if "deleted collection" in response_content:
            response_content["deleted collection"] = response_content["deleted collection"].removeprefix(f"{user}_")
        # delete the s3 files as well
        await self.s3_manager().delete_s3_files(self.s3_files_to_be_deleted)
        self.s3_files_to_be_deleted.clear()
        return JSONResponse(response_content, HTTP_200_OK, headers_minus_content_length(response))
