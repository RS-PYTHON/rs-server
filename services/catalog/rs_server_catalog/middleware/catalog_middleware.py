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

from typing import Any, cast

from fastapi import HTTPException
from rs_server_catalog.data_management.user_handler import get_user, reroute_url
from rs_server_catalog.middleware.request_manager import CatalogRequestManager
from rs_server_catalog.middleware.response_manager import CatalogResponseManager
from rs_server_common import settings as common_settings
from rs_server_common.utils.logging import Logging
from stac_fastapi.pgstac.app import api
from stac_fastapi.pgstac.core import CoreCrudClient
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

logger = Logging.default(__name__)


class CatalogMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """The user catalog middleware."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Redirect the user catalog specific endpoint and adapt the response content."""
        # NOTE: maybe we could move the UserCatalog.dispatch here but I'm not sure it's thread-safe.
        # Maybe this is the reason why we init a new UserCatalog instance everytime. To be confirmed.
        return await UserCatalog(api.client).dispatch(request, call_next)


class UserCatalog:  # pylint: disable=too-few-public-methods
    """The user catalog middleware handler."""

    def __init__(self, client: CoreCrudClient):
        """Constructor, called from the middleware"""
        self.request_ids: dict[Any, Any] = {}
        self.client = client

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """
        Redirect the user catalog specific endpoint and adapt the response content.

        Args:
            request (Request): Initial request
            call_next: next call to apply

        Returns:
            response (Response): Response to the current request
        """
        request_body = None if request.method not in ["PATCH", "POST", "PUT"] else await request.json()
        auth_roles = user_login = owner_id = None

        # ---------- Management of  authentification (retrieve user_login + default owner_id)
        if common_settings.CLUSTER_MODE:  # Get the list of access and the user_login calling the endpoint.
            try:
                auth_roles = request.state.auth_roles
                user_login = request.state.user_login
            # Case of endpoints that do not call the authenticate function
            # Get the the user_login calling the endpoint. If this is not set (the authentication.authenticate function
            # is not called), the local user shall be used (later on, in rereoute_url)
            # The common_settings.CLUSTER_MODE may not be used because for some endpoints like /api
            # the authenticate is not called even if common_settings.CLUSTER_MODE is True. Thus, the presence of
            # user_login has to be checked instead
            except (NameError, AttributeError):
                auth_roles = []
                user_login = get_user(None, None)  # Get default local or cluster user
        elif common_settings.LOCAL_MODE:
            user_login = get_user(None, None)
        owner_id = ""  # Default owner_id is empty
        logger.debug(
            f"Received {request.method} from '{user_login}' | {request.url.path}?{request.query_params}",
        )

        # ---------- Request rerouting
        # Dictionary to easily access main data from the request
        self.request_ids = {
            "auth_roles": auth_roles,
            "user_login": user_login,
            "owner_id": owner_id,
            "collection_ids": [],
            "item_id": "",
        }
        reroute_url(request, self.request_ids)
        if not request.scope["path"]:  # Invalid endpoint
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Invalid endpoint.")
        logger.debug(f"path = {request.scope['path']} | requests_ids = {self.request_ids}")

        # Ensure that user_login is not null after rerouting
        if not self.request_ids["user_login"]:
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail="user_login is not defined !",
            )

        # ---------- Body data recovery
        # Recover user and collection id with the ones provided in the request body
        # (if the corresponding parameters have not been recovered from the url)
        # This is available in POST/PUT/PATCH methods only
        if request_body:
            # Edit owner_id with the corresponding body content if exist
            if not self.request_ids["owner_id"]:
                self.request_ids["owner_id"] = request_body.get("owner")
            # received a POST/PUT/PATCH for a STAC item or
            # a STAC collection is created
            if len(self.request_ids["collection_ids"]) == 0:
                collections = request_body.get("collections") or request_body.get("id")
                if collections:
                    self.request_ids["collection_ids"] = collections if isinstance(collections, list) else [collections]

            if not self.request_ids["item_id"] and request_body.get("type") == "Feature":
                self.request_ids["item_id"] = request_body.get("id")

        # ---------- Apply specific changes for each endpoint

        request_manager = CatalogRequestManager(self.client, self.request_ids)
        request = await request_manager.manage_requests(request)
        # If the request manager returns a response, it usually means the user is not authorized
        # to do the operation received, so we directly return the response
        if isinstance(request, Response):
            return request

        response = await call_next(request)

        response_manager = CatalogResponseManager(
            request_manager.client,
            request_manager.request_ids,
            request_manager.s3_files_to_be_deleted,
        )
        return await response_manager.manage_responses(request, cast(StreamingResponse, response))
