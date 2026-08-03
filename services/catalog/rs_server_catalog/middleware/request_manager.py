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

"""Module to process the Requests sent by users to the Catalog before routing them to stac-fastapi."""

import copy
import getpass
import json
import os
from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast
from urllib.parse import urlencode

import cql2
from fastapi import HTTPException
from rs_server_catalog.authentication_catalog import (
    check_user_authorization,
    get_authorisation,
)
from rs_server_catalog.data_management import timestamps_extension
from rs_server_catalog.data_management.geometry_manager import (
    validate_geometry_and_enforce_bbox,
)
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
from rs_server_common.authentication import authentication
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
    HTTP_500_INTERNAL_SERVER_ERROR,
)

logger = Logging.default(__name__)

# Number of complete S3 cleanup retries before a catalog DELETE reaches pgSTAC.
# A value of 1 means one retry after the initial cleanup attempt.
CATALOG_DELETE_MAX_RETRIES = max(0, int(os.environ.get("RSPY_CATALOG_DELETE_MAX_RETRIES", "0")))


def enforce_pgstac_defaults_for_null_geometry(content: dict[str, Any]) -> dict[str, Any]:
    """
    Inject internal default geometry/bbox when both are null.

    pgstac stores item geometry in a NOT NULL column, while RS Server must keep
    accepting upstream items without spatial metadata. The default geometry is
    therefore an internal persistence shim and is masked again in responses.
    """
    if content.get("geometry") is None and content.get("bbox") is None:
        logger.debug("Injecting pgstac default geometry/bbox for item %s", content.get("id"))
        content["geometry"] = copy.deepcopy(DEFAULT_GEOM)
        content["bbox"] = copy.deepcopy(DEFAULT_BBOX)
    return content


def iter_external_id_parts(raw: Any) -> list[str]:
    """
    Split externalIds input into clean tokens.

    Clients may send `externalIds` as a single string, a comma-separated string,
    or a list. Normalizing early lets GET query params and POST bodies share the
    same filter-building path.
    """
    parts: list[str] = []
    values = raw if isinstance(raw, list) else [raw]
    for value in values:
        # Allow callers to pass a single string with comma-separated ids.
        for part in str(value or "").split(","):
            part = part.strip()
            if part:
                parts.append(part)
    return parts


def build_external_ids_tokens(raw: Any) -> list[str]:
    """
    Normalize externalIds values into the token representation stored by pgstac.

    Supported input forms are `scheme:value`, `scheme:`, `:value`, plain value,
    and comma-separated/list combinations. Duplicates are removed while keeping
    the original order for predictable debugging.
    """
    tokens: list[str] = []
    seen: set[str] = set()
    for part in iter_external_id_parts(raw):
        token = None
        if ":" in part:
            scheme, value = part.split(":", 1)
            scheme = scheme.strip()
            value = value.strip()
            # Keep scheme:value, scheme-only, or value-only depending on input form.
            if scheme and value:
                token = f"{scheme}:{value}"
            elif scheme and not value:
                token = scheme
            elif value and not scheme:
                token = value
        else:
            # No scheme provided, keep raw value.
            token = part
        if token and token not in seen:
            tokens.append(token)
            seen.add(token)
    logger.debug("Normalized externalIds input %s to tokens %s", raw, tokens)
    return tokens


def build_external_ids_filter(raw: Any) -> dict | None:
    """Create a CQL2 `a_overlaps` filter for normalized externalIds tokens."""
    tokens = build_external_ids_tokens(raw)
    if not tokens:
        return None
    # pgstac expects array overlap when querying token arrays.
    return {"op": "a_overlaps", "args": [{"property": "externalIds"}, tokens]}


def parse_filter_to_json(raw_filter: Any, filter_lang: str) -> dict | None:
    """
    Normalize a CQL2 filter to CQL2-JSON.

    The catalog middleware rewrites some filters before forwarding the request
    to pgstac. Working in JSON form avoids brittle string manipulation and keeps
    GET and POST behavior aligned.
    """
    if raw_filter is None:
        return None
    if isinstance(raw_filter, dict):
        return raw_filter
    if isinstance(raw_filter, str):
        try:
            if filter_lang == "cql2-text":
                # cql2 exposes either parse_text or parse depending on version.
                parser = getattr(cql2, "parse_text", None) or getattr(cql2, "parse", None)
                if parser is None or not callable(parser):
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail="CQL2 text parser is not available.",
                    )
                cql2_text_parser = cast(Callable[[str], Any], parser)
                # pylint can't infer the callable from getattr; runtime is safe after callable() check.
                return cql2_text_parser(raw_filter).to_json()  # pylint: disable=not-callable
            return json.loads(raw_filter)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=(
                    "Invalid filter format for externalIds search: "
                    f"raw_filter={raw_filter!r}, filter_lang={filter_lang!r}"
                ),
            ) from exc
    return None


def combine_filters(existing: dict | None, extra: dict) -> dict:
    """Combine two CQL2 filters with AND, preserving an existing filter when present."""
    if existing is None:
        return extra
    return {"op": "and", "args": [existing, extra]}


def filter_has_external_ids(filter_json: Any) -> bool:
    """Recursively check whether a CQL2 filter tree references `externalIds`."""
    if isinstance(filter_json, dict):
        if filter_json.get("property") == "externalIds":
            return True
        # Recursively scan nested operations/arguments.
        return any(filter_has_external_ids(value) for value in filter_json.values())
    if isinstance(filter_json, list):
        # Lists can hold nested filter nodes.
        return any(filter_has_external_ids(item) for item in filter_json)
    return False


def normalize_external_ids_in_filter(filter_json: dict) -> dict:
    """
    Rewrite externalIds comparisons into array-overlap filters.

    pgstac stores `externalIds` as an array of tokens. Equality/in filters sent
    by clients therefore need to become `a_overlaps` filters to match the stored
    representation.
    """
    if not isinstance(filter_json, dict):
        return filter_json
    op = filter_json.get("op")
    if op in ("and", "or", "not"):
        # Walk the boolean tree and normalize only the externalIds leaf comparisons.
        args = filter_json.get("args", [])
        if isinstance(args, list):
            return {**filter_json, "args": [normalize_external_ids_in_filter(arg) for arg in args]}
        return filter_json
    if op in ("=", "==", "eq", "in"):
        # STAC Browser sends "externalIds = <uuid>", but pgstac stores externalIds as an array of tokens.
        # Using "=" against an array yields no matches, so we convert it to a_overlaps on token list.
        args = filter_json.get("args", [])
        if isinstance(args, list) and len(args) == 2:
            left, right = args
            if isinstance(left, dict) and left.get("property") == "externalIds":
                # Normalize raw values (string, list, comma-separated) to tokens.
                tokens = build_external_ids_tokens(right)
                if tokens:
                    return {"op": "a_overlaps", "args": [{"property": "externalIds"}, tokens]}
            if isinstance(right, dict) and right.get("property") == "externalIds":
                # Support the (value, property) argument order too.
                tokens = build_external_ids_tokens(left)
                if tokens:
                    return {"op": "a_overlaps", "args": [{"property": "externalIds"}, tokens]}
    return filter_json


def normalize_external_ids_filter_value(raw_filter: Any, filter_lang: str) -> tuple[Any, str, bool]:
    """
    Normalize any externalIds expression inside a filter value.

    Returns:
        Tuple `(filter, filter_lang, changed)` where `changed` tells callers
        whether the request body/query string must be rewritten.
    """
    if raw_filter is None:
        return raw_filter, filter_lang, False
    if isinstance(raw_filter, str) and "externalIds" not in raw_filter:
        return raw_filter, filter_lang, False
    # Parse to JSON so we can rewrite externalIds operators for pgstac.
    filter_json = parse_filter_to_json(raw_filter, filter_lang)
    if filter_json is None or not filter_has_external_ids(filter_json):
        return raw_filter, filter_lang, False
    # Convert externalIds comparisons to array-overlap filters (a_overlaps).
    normalized = normalize_external_ids_in_filter(filter_json)
    logger.debug(
        "Normalized externalIds filter from lang=%s filter=%s to lang=cql2-json filter=%s",
        filter_lang,
        raw_filter,
        normalized,
    )
    return normalized, "cql2-json", True


class CatalogRequestManager:
    """
    Pre-process catalog requests before they are routed to stac-fastapi.

    Responsibilities include owner/collection authorization, frontend-to-pgstac
    route/body/query rewriting, S3 publication validation, and deleting S3
    assets before DELETE mutations reach pgstac.
    """

    def __init__(self, client: CoreCrudClient, request_ids: dict[Any, Any]):
        self.client = client
        self.request_ids = request_ids
        self.s3_files_to_be_deleted: list = []

    @lru_cache
    def s3_manager(self, request: Request):
        """
        Creates a cached instance of S3Manager for this class instance (self).
        Use S3 object storage credentials of the logged user.
        """
        return S3Manager(authentication.get_s3_credentials(request))

    def _override_request_body(self, request: Request, content: Any) -> Request:
        """
        Replace the request body consumed by downstream stac-fastapi.

        Starlette caches parsed body/json on the Request object. When middleware
        changes catalog ids, timestamps or filters, both cached values must be
        updated so later handlers observe the rewritten payload.
        """
        request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access
        request._json = content  # pylint: disable=protected-access
        logger.info(
            "Overrode catalog request body for %s %s; owner=%s, collections=%s, item=%s",
            request.method,
            request.scope["path"],
            self.request_ids.get("owner_id"),
            self.request_ids.get("collection_ids"),
            self.request_ids.get("item_id"),
        )
        logger.debug("new request body and json: %s", request._body)  # pylint: disable=protected-access
        return request

    def _override_request_query_string(self, request: Request, query_params: dict) -> Request:
        """
        Replace the request query string consumed by downstream stac-fastapi.

        Query parameters are rewritten after owner resolution and filter
        normalization, then re-encoded with doseq support for list-like values.
        """
        request.scope["query_string"] = urlencode(query_params, doseq=True).encode("utf-8")
        logger.info("Overrode catalog query string for %s %s", request.method, request.scope["path"])
        logger.debug("Updated catalog query params: %s", query_params)
        logger.debug("new request query_string: %s", request.scope["query_string"])
        return request

    async def _collection_exists(self, request: Request, collection_id: str) -> bool:
        """Check if the collection exists.

        Returns:
            bool: True if the collection exists, False otherwise
        """
        try:
            logger.debug("Checking collection existence for %s", collection_id)
            await self.client.get_collection(collection_id, request)
            logger.debug("Collection %s exists", collection_id)
            return True
        except Exception:  # pylint: disable=broad-exception-caught
            logger.debug("Collection %s does not exist or cannot be retrieved", collection_id)
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
            logger.debug("Retrieving item %s from collection %s", item_id, collection_id)
            item = await self.client.get_item(item_id=item_id, collection_id=collection_id, request=request)
            logger.info("Retrieved existing item %s from collection %s", item_id, collection_id)
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
        """
        Build the S3 cleanup list for DELETE requests.

        Collection deletes require scanning all items in the collection, while
        item deletes only need the requested item. The resulting list is deleted
        before the request is forwarded to pgstac.
        """
        logger.info(
            "Building S3 deletion list for owner=%s collections=%s item=%s",
            self.request_ids["owner_id"],
            self.request_ids["collection_ids"],
            self.request_ids["item_id"],
        )
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
                        logger.debug(
                            "Fetched %d item(s) for deletion scan from collection %s; token=%s",
                            len(items_collection.get("features", [])),
                            collection_id,
                            token,
                        )
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
                raise HTTPException(
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to prepare S3 cleanup; catalog metadata was not deleted.",
                ) from e
            logger.debug(f"Found {len(items)} items: {items}")
            try:
                for item in items:
                    assets = item.get("assets", {})
                    for _, asset_info in assets.items():
                        s3_href = asset_info.get("href")
                        if s3_href:
                            self.s3_files_to_be_deleted.append(s3_href)
                            logger.debug("Scheduled S3 deletion for %s", s3_href)
            except KeyError as e:
                logger.error(
                    f"Failed to build the list of S3 files to be deleted due to missing key in dictionary: {e}",
                )
                raise HTTPException(
                    status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to prepare S3 cleanup; catalog metadata was not deleted.",
                ) from e
            logger.info(
                "Successfully built the list of S3 files to be deleted. "
                f"There are {len(self.s3_files_to_be_deleted)} files to be deleted",
            )

    async def manage_requests(self, request: Request) -> Request | Response:
        """
        Dispatch catalog request pre-processing by method/path.

        This is the main entry point used by CatalogMiddleware. It keeps the
        endpoint-specific transformations isolated while returning either the
        rewritten Request or an early Response when authorization fails.

        Args:
            request (Request): request received by the Catalog.

        Returns:
            Request|Response: Request processed to be sent to stac-fastapi OR a response if the operation
                is not authorized
        """
        logger.info(
            "Managing catalog request %s %s; owner=%s, collections=%s, item=%s",
            request.method,
            request.scope["path"],
            self.request_ids["owner_id"],
            self.request_ids["collection_ids"],
            self.request_ids["item_id"],
        )
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
        """
        Adapt POST/PUT request bodies for stac-fastapi.

        Collection writes get owner-prefixed ids and timestamps. Item writes
        validate authorization, collection existence, geometry/bbox consistency,
        S3 availability and checksums before the request is forwarded.

        Args:
            request (Request): The Client request to be updated.

        Returns:
            Request: The request updated.
        """
        try:
            original_content = await request.json()
            content = copy.deepcopy(original_content)
            logger.info(
                "Managing %s catalog write request for owner=%s collections=%s item=%s",
                request.method,
                self.request_ids["owner_id"],
                self.request_ids["collection_ids"],
                self.request_ids["item_id"],
            )
            logger.debug("Original catalog write content: %s", original_content)

            check_user_authorization(self.request_ids)
            logger.debug("Catalog write authorization succeeded for request ids %s", self.request_ids)

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
                logger.info("Preparing collection %s for catalog write", content["id"])

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
                logger.info(
                    "Preparing item %s for publication/update in collection %s",
                    content.get("id"),
                    collection,
                )
                # first check if the collection exists
                if not await self._collection_exists(request, f"{self.request_ids['owner_id']}_{collection}"):
                    raise HTTPException(
                        status_code=HTTP_404_NOT_FOUND,
                        detail=f"Collection {collection} does not exist.",
                    )

                # try to get the item if it is already part from the collection
                item = await self._get_item_from_collection(request)
                content = self.s3_manager(request).update_stac_item_publication(
                    content,
                    request,
                    self.request_ids,
                    item,
                )
                logger.debug(
                    "Checking if all item assets are available in S3 before allowing the publication of the item",
                )

                # Geometry checks and bbox enforcement are done before any S3 side effect.
                logger.debug("Validating geometry/bbox for item %s", content.get("id"))
                content = validate_geometry_and_enforce_bbox(content)
                # Keep ESA behavior (accept null geometry+bbox) while ensuring pgstac persistence compatibility.
                content = enforce_pgstac_defaults_for_null_geometry(content)

                if not self.s3_manager(request).check_if_item_can_be_published(content):
                    logger.debug("The item cannot be published because some of its assets are not yet available in S3")
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail=f"Not all assets for item {content['id']} are available in S3.",
                    )
                logger.debug("All assets of the item are available in S3, the item can be published or updated")
                logger.info("All assets are available for catalog item %s", content.get("id"))
                content = self.s3_manager(request).update_assets_checksums(content)
                if content:
                    if request.method == "POST":
                        content = timestamps_extension.set_timestamps_for_creation(content)
                        content = timestamps_extension.set_timestamps_for_insertion(content)
                        logger.debug("Set creation/insertion timestamps for item %s", content.get("id"))
                    else:  # PUT
                        published = ""
                        if item and item.get("properties"):
                            published = item["properties"].get("published", "")
                        logger.debug("Got published = %s", published)
                        if not published:
                            raise HTTPException(
                                status_code=HTTP_400_BAD_REQUEST,
                                detail=f"Item {content['id']} not found.",
                            )
                        content = timestamps_extension.set_timestamps_for_update(
                            content,
                            original_published=published,
                        )
                        logger.debug("Set update timestamps for item %s", content.get("id"))
                if hasattr(content, "status_code"):
                    return content

            # update request body if needed
            if content != original_content:
                request = self._override_request_body(request, content)

            logger.debug(f"Sending back the response for {request.method} {request.scope['path']}")
            logger.info("Finished managing %s catalog write request for %s", request.method, request.scope["path"])
            return request  # pylint: disable=protected-access
        except KeyError as kerr_msg:
            logger.exception("Catalog write request is missing expected key: %s", kerr_msg)
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
        logger.info(
            "Managing delete request for owner=%s collections=%s item=%s as user=%s",
            self.request_ids["owner_id"],
            self.request_ids["collection_ids"],
            self.request_ids["item_id"],
            user_login,
        )

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
            logger.warning(
                "Delete request denied by authorization; owner=%s collections=%s user=%s",
                self.request_ids["owner_id"],
                self.request_ids["collection_ids"],
                user_login,
            )
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
        # Retry count excludes the initial attempt; range's upper bound is exclusive.
        max_attempts = CATALOG_DELETE_MAX_RETRIES + 1
        for attempt in range(1, max_attempts + 1):
            # Rebuild from catalog metadata on every outer attempt. A previous
            # S3 attempt may have deleted only part of a large asset prefix.
            self.s3_files_to_be_deleted.clear()
            await self.build_filelist_to_be_deleted(request)
            try:
                logger.info(
                    "Deleting %d S3 asset target(s) before catalog metadata for %s (outer attempt %d/%d)",
                    len(self.s3_files_to_be_deleted),
                    request.scope["path"],
                    attempt,
                    max_attempts,
                )
                await self.s3_manager(request).delete_s3_files(self.s3_files_to_be_deleted)
                break
            except RuntimeError as exc:
                if attempt >= max_attempts:
                    logger.exception(
                        "S3 cleanup failed before catalog DELETE for %s after %d outer attempt(s)",
                        request.scope["path"],
                        max_attempts,
                    )
                    raise HTTPException(
                        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to delete S3 assets; catalog metadata was not deleted.",
                    ) from exc
                logger.warning(
                    "S3 cleanup attempt %d/%d failed for %s: %s. Rebuilding targets and retrying from scratch.",
                    attempt,
                    max_attempts,
                    request.scope["path"],
                    exc,
                )

        self.s3_files_to_be_deleted.clear()
        logger.info("Delete request authorized for %s", request.scope["path"])
        return True

    async def manage_search_request(  # pylint: disable=too-many-statements,too-many-branches
        self,
        request: Request,
    ) -> Request | JSONResponse:
        """
        Normalize catalog search requests and resolve owner-prefixed collections.

        The search endpoint accepts owner hints from URL path, query/body owner,
        collections and CQL2 filters. This method resolves those hints, rewrites
        collections to pgstac ids, normalizes `externalIds`, and checks read
        authorization before forwarding the request.

        Args:
            request Request: the client request.

        Returns:
            Request: the new request with the collection name updated.
        """
        # ---------- POST requests
        if request.method == "POST":
            content = await request.json()
            original_content = copy.deepcopy(content)
            logger.info("Managing POST catalog search request")
            logger.debug("Original POST search body: %s", original_content)

            # Normalize externalIds filters coming from UI (e.g., "=" -> a_overlaps).
            normalized_filter, normalized_lang, changed = normalize_external_ids_filter_value(
                content.get("filter"),
                content.get("filter-lang", "cql2-json"),
            )
            if changed:
                content["filter"] = normalized_filter
                content["filter-lang"] = normalized_lang
                logger.info("Normalized externalIds filter for POST catalog search")

            # Build a CQL2 filter for externalIds (array of objects) if requested.
            external_ids_filter = build_external_ids_filter(content.pop("externalIds", None))
            if external_ids_filter is not None:
                existing_filter = parse_filter_to_json(
                    content.get("filter"),
                    content.get("filter-lang", "cql2-json"),
                )
                content["filter"] = combine_filters(existing_filter, external_ids_filter)
                content["filter-lang"] = "cql2-json"
                logger.info("Added externalIds filter to POST catalog search")

            # Pre-processing of filter extensions
            if "filter" in content:
                content["filter"] = process_filter_extensions(content["filter"])
                logger.debug("Processed POST search filter extensions: %s", content["filter"])

            # Management of priority for the assignation of the owner_id
            if not self.request_ids["owner_id"]:
                self.request_ids["owner_id"] = (
                    (extract_owner_name_from_json_filter(content["filter"]) if "filter" in content else None)
                    or content.get("owner")
                    or get_user(self.request_ids["owner_id"], self.request_ids["user_login"])
                )
                logger.debug("POST search owner resolved to %s", self.request_ids["owner_id"])

            # Ensure normalized filters are serialized in request body.
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
                    normalized = collection.replace(":", "_")
                    owner_prefixed = f"{self.request_ids['owner_id']}_{normalized}"

                    if await self._collection_exists(request, normalized):
                        content["collections"][i] = normalized
                    elif await self._collection_exists(request, owner_prefixed):
                        content["collections"][i] = owner_prefixed
                        logger.debug(f"Using collection name: {content['collections'][i]}")
                    else:
                        raise HTTPException(
                            status_code=HTTP_404_NOT_FOUND,
                            detail=f"Collection {collection} not found.",
                        )

                self.request_ids["collection_ids"] = content["collections"]
                logger.info("POST search collections resolved to %s", self.request_ids["collection_ids"])
            if content != original_content:
                request = self._override_request_body(request, content)

        # ---------- GET requests
        elif request.method == "GET":
            # Get dictionary of query parameters
            query_params_dict = dict(request.query_params)
            original_query_params = dict(query_params_dict)
            logger.info("Managing GET catalog search request")
            logger.debug("Original GET search query params: %s", original_query_params)

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
                logger.debug("GET search owner resolved to %s", self.request_ids["owner_id"])

            # Normalize externalIds filters coming from UI (e.g., "=" -> a_overlaps).
            normalized_filter, normalized_lang, changed = normalize_external_ids_filter_value(
                query_params_dict.get("filter"),
                query_params_dict.get("filter-lang", "cql2-json"),
            )
            if changed:
                query_params_dict["filter"] = json.dumps(normalized_filter)
                query_params_dict["filter-lang"] = normalized_lang
                logger.info("Normalized externalIds filter for GET catalog search")

            # Build a CQL2 filter for externalIds (array of objects) if requested.
            external_ids_filter = build_external_ids_filter(query_params_dict.pop("externalIds", None))
            if external_ids_filter is not None:
                existing_filter = parse_filter_to_json(
                    query_params_dict.get("filter"),
                    query_params_dict.get("filter-lang", "cql2-json"),
                )
                combined_filter = combine_filters(existing_filter, external_ids_filter)
                query_params_dict["filter"] = json.dumps(combined_filter)
                query_params_dict["filter-lang"] = "cql2-json"
                logger.info("Added externalIds filter to GET catalog search")

            # ----- Catch endpoint catalog/search + query parameters (e.g. /search?ids=S3_OLC&collections=titi)
            if "collections" in query_params_dict:
                coll_list = query_params_dict["collections"].split(",")

                # Check if each collection exist with their raw name, if not concatenate owner_id to the collection name
                for i, collection in enumerate(coll_list):
                    # Handle case when user is specified in ?collections=user:collection
                    normalized = collection.replace(":", "_")
                    owner_prefixed = f"{self.request_ids['owner_id']}_{normalized}"

                    if await self._collection_exists(request, normalized):
                        coll_list[i] = normalized
                    elif await self._collection_exists(request, owner_prefixed):
                        coll_list[i] = owner_prefixed
                        logger.debug(f"Using collection name: {owner_prefixed}")
                    else:
                        raise HTTPException(
                            status_code=HTTP_404_NOT_FOUND,
                            detail=f"Collection {collection} not found.",
                        )

                self.request_ids["collection_ids"] = coll_list
                query_params_dict["collections"] = ",".join(coll_list)
                logger.info("GET search collections resolved to %s", self.request_ids["collection_ids"])
            if query_params_dict != original_query_params:
                request = self._override_request_query_string(request, query_params_dict)

        # Check that the collection from the request exists
        for collection in self.request_ids["collection_ids"]:
            if not await self._collection_exists(request, collection):
                raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Collection {collection} not found.")
        logger.debug("Catalog search request ids after management: %s", self.request_ids)

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
            logger.info("Catalog search authorization succeeded for user %s", self.request_ids["user_login"])
        return request

    async def manage_patch_request(self, request: Request):
        """
        Pre-processing of a PATCH request to the Catalog.

        Does authorization checks, merges partial geometry/bbox patches with the
        current item when necessary, enforces spatial consistency, and updates
        the `updated` timestamp.

        Args:
            request (Request): The request from the Client

        Returns:
            Request: Updated request
        """
        try:
            original_content = await request.json()
            content = copy.deepcopy(original_content)
            logger.info(
                "Managing PATCH catalog request for owner=%s collections=%s item=%s",
                self.request_ids["owner_id"],
                self.request_ids["collection_ids"],
                self.request_ids["item_id"],
            )
            logger.debug("Original PATCH body: %s", original_content)

            check_user_authorization(self.request_ids)
            logger.debug("PATCH authorization succeeded for request ids %s", self.request_ids)

            is_item = "/items/" in request.scope["path"]
            if is_item and ("geometry" in content or "bbox" in content):
                # Load current item because PATCH payload can contain only partial geometry/bbox fields.
                item = await self._get_item_from_collection(request)
                if not item:
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail=f"Item {self.request_ids['item_id']} not found.",
                    )

                # Merge patched geometry/bbox over current item, then validate the result.
                logger.debug("Merging PATCH geometry/bbox over current item %s", self.request_ids["item_id"])
                merged_content = copy.deepcopy(item)
                if "geometry" in content:
                    merged_content["geometry"] = content["geometry"]
                    # Force bbox recomputation/removal according to the new geometry.
                    if "bbox" not in content:
                        merged_content["bbox"] = None
                if "bbox" in content:
                    merged_content["bbox"] = content["bbox"]

                merged_content = validate_geometry_and_enforce_bbox(merged_content)
                # Keep ESA behavior for null geometry+bbox while making PATCH payload acceptable for pgstac.
                merged_content = enforce_pgstac_defaults_for_null_geometry(merged_content)
                # Propagate enforced geometry/bbox back to patch body so stored item stays consistent.
                content["geometry"] = merged_content.get("geometry", None)
                content["bbox"] = merged_content.get("bbox", None)
                logger.debug(
                    "PATCH geometry/bbox enforced for item %s: geometry=%s bbox=%s",
                    self.request_ids["item_id"],
                    content.get("geometry"),
                    content.get("bbox"),
                )

            # Update "updated" timestamp (different field if it is an item or a collection)
            content = timestamps_extension.set_updated_timestamp_to_now(content, is_item=is_item)
            logger.debug("Updated PATCH timestamp for item=%s", is_item)

            request = self._override_request_body(request, content)
            logger.info("Finished managing PATCH request for %s", request.scope["path"])
            return request

        except KeyError as kerr_msg:
            logger.exception("PATCH request is missing expected key: %s", kerr_msg)
            raise HTTPException(
                detail=f"Missing key in request body! {kerr_msg}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from kerr_msg
