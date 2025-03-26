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
import os
import traceback
from collections.abc import Callable
from typing import TypedDict

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from rs_server_common import settings as common_settings
from rs_server_common.authentication import authentication, oauth2
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.authentication.oauth2 import AUTH_PREFIX, LoginAndRedirect
from rs_server_common.utils.logging import Logging
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

logger = Logging.default(__name__)


class ErrorResponse(TypedDict):
    """A JSON error response returned by the API.

    The STAC API spec expects that `code` and `description` are both present in
    the payload.

    Attributes:
        code: A code representing the error, semantics are up to implementor.
        description: A description of the error.
    """

    code: str
    description: str


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
            return (
                JSONResponse(
                    content=ErrorResponse(code=exception.__class__.__name__, description=str(exception)),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
                if self.is_bad_request(request, exception)
                else JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=str(exception))
            )

    def is_bad_request(self, request: Request, e: Exception) -> bool:
        """Determines if the request that raised this exception shall be considered as a bad request"""
        return "bbox" in request.query_params and (
            str(e).endswith(" must have 4 or 6 values.") or str(e).startswith("could not convert string to float: ")
        )


def apply_middlewares(app: FastAPI):
    """
    Applies necessary middlewares and authentication routes to the FastAPI application.

    This function ensures that:
    1. `SessionMiddleware` is inserted after `HandleExceptionsMiddleware` to enable cookie storage.
    2. OAuth2 authentication routes are added to the FastAPI application.

    Args:
        app (FastAPI): The FastAPI application instance.

    Raises:
        RuntimeError: If the function is called after the application has already started.

    Returns:
        FastAPI: The modified FastAPI application instance with the required middleware and authentication routes.
    """
    # Existing middlewares
    middleware_names = [middleware.cls.__name__ for middleware in app.user_middleware]  # type: ignore

    # Insert the SessionMiddleware (to save cookies) after the HandleExceptionsMiddleware middleware.
    # Code copy/pasted from app.add_middleware(SessionMiddleware, secret_key=cookie_secret)
    if app.middleware_stack:
        raise RuntimeError("Cannot add middleware after an application has started")
    middleare_index = middleware_names.index("HandleExceptionsMiddleware")
    cookie_secret = os.environ["RSPY_COOKIE_SECRET"]
    app.user_middleware.insert(middleare_index + 1, Middleware(SessionMiddleware, secret_key=cookie_secret))

    # Get the oauth2 router
    oauth2_router = oauth2.get_router(app)

    # Add it to the FastAPI application
    app.include_router(
        oauth2_router,
        tags=["Authentication"],
        prefix=AUTH_PREFIX,
        include_in_schema=True,
    )
    return app
