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

"""Common functions for fastapi middlewares"""
import traceback
from typing import Callable

from fastapi import Request, status
from fastapi.responses import JSONResponse
from rs_server_common import settings as common_settings
from rs_server_common.authentication import authentication, oauth2
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.authentication.oauth2 import LoginAndRedirect
from rs_server_common.utils.logging import Logging
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

logger = Logging.default(__name__)


class AuthenticationMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """
    Implement authentication verification.
    """

    def __init__(self, app, must_be_authenticated, dispatch=None):
        self.must_be_authenticated = must_be_authenticated
        super().__init__(app, dispatch)

    async def dispatch(self, request: Request, call_next: Callable):
        """
        Middleware implementation.
        """

        if common_settings.CLUSTER_MODE and self.must_be_authenticated(request.url.path):
            try:
                # Check the api key validity, passed in HTTP header, or oauth2 autentication (keycloak)
                await authentication.authenticate(
                    request=request,
                    apikey_value=request.headers.get(APIKEY_HEADER, None),
                )

            # Login and redirect to the calling endpoint.
            except LoginAndRedirect:
                return await oauth2.login(request)

        # Call the next middleware
        return await call_next(request)


class HandleExceptionsMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """
    Middleware to catch all exceptions and return a JSONResponse instead of raising them.
    This is useful in FastAPI when HttpExceptions are raised within the code but need to be handled gracefully.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            return await call_next(request)
        except StarletteHTTPException as http_exception:
            # Log stack trace and return HTTP exception details
            logger.error(traceback.format_exc())
            return JSONResponse(status_code=http_exception.status_code, content=str(http_exception.detail))
        except Exception as exception:  # pylint: disable=broad-exception-caught
            # Log stack trace and return generic error response
            logger.error(traceback.format_exc())
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content=str(exception),
            )
