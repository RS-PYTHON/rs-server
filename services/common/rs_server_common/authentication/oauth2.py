# Copyright 2023-2024, CS GROUP - France, https://www.csgroup.eu/
#
# This file is part of APIKeyManager project
#     https://github.com/csgroup-oss/apikey-manager/
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
from typing import Annotated
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from authlib.integrations import starlette_client
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse
from rs_server_common import settings
from rs_server_common.authentication.keycloak_util import KCUtil
from rs_server_common.utils.utils2 import AuthInfo
from starlette.config import Config as StarletteConfig
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

# authlib object for oauth2 keycloak authentication
KEYCLOAK: StarletteOAuth2App = None

# Const values
AUTH_PREFIX = "/auth"
LOGIN_FROM_BROWSER = "/login"
LOGIN_FROM_CONSOLE = "/login_from_console"
COOKIE_NAME = "user"
SWAGGER_HOMEPAGE = "/docs"  # swagger /docs page as called from the cluster


class LoginAndRedirect(Exception):
    """
    Used to call the login endpoint and redirect to the calling endpoint.
    See https://github.com/fastapi/fastapi/discussions/7817#discussioncomment-5144391
    """

    pass


async def is_logged_in(request: Request) -> bool:
    """We know that the user is logged in if the session cookie exists."""
    return COOKIE_NAME in request.session


async def console_logged_message() -> HTMLResponse:
    """Message sent to the user when they are already logged in from the python console."""
    return HTMLResponse("You are logged in.")


async def login(request: Request):
    """
    Login using oauth2 from either a browser or a python console.
    """
    calling_endpoint = request.url
    called_from_console = calling_endpoint.path.rstrip("/") == f"{AUTH_PREFIX}{LOGIN_FROM_CONSOLE}"

    # If the user is already logged in
    if await is_logged_in(request):
        if called_from_console:
            return await console_logged_message()

        # If the /login endpoint was called from the browser, redirect to the Swagger UI
        if calling_endpoint.path.rstrip("/") == f"{AUTH_PREFIX}{LOGIN_FROM_BROWSER}":
            return RedirectResponse(SWAGGER_HOMEPAGE)

        # For other endpoints called from the browser, redirect to this endpoint
        return RedirectResponse(calling_endpoint)

    # Code and state coming from keycloak
    code = request.query_params.get("code")
    state = request.query_params.get("state")

    # If they are not set, then we need to call keycloak,
    # which then will call again this endpiont.
    if (not code) and (not state):
        response = await KEYCLOAK.authorize_redirect(request, calling_endpoint)

        # If called from a console, return the login page url so the caller can display it itself.
        if called_from_console:
            return response.headers["location"]

        # From a browser, make the redirection in the current browser tab
        return response

    # Else we are called from keycloak.
    # In a session cookie, we save the user information received from keycloak.
    token = await KEYCLOAK.authorize_access_token(request)
    userinfo = dict(token["userinfo"])
    request.session[COOKIE_NAME] = userinfo

    # Redirect to the calling endpoint after removing the authentication query parameters from the URL.
    # See: https://stackoverflow.com/a/7734686
    url = urlparse(str(calling_endpoint))
    query = parse_qs(url.query, keep_blank_values=True)
    for param in ["state", "session_state", "iss", "code"]:
        query.pop(param, None)
    url = url._replace(query=urlencode(query, True))
    return RedirectResponse(urlunparse(url))


def get_router(app: FastAPI) -> APIRouter:
    """
    Set and return the FastAPI router that implements the endpoints for oauth2 authentication."

    Args:
        app (FastAPI): FastAPI application

    Returns:
        APIRouter: FastAPI router, to be added to the FastAPI application.
    """

    # Returned router
    router = APIRouter()

    # Read environment variables
    oidc_endpoint = os.environ["OIDC_ENDPOINT"]
    oidc_realm = os.environ["OIDC_REALM"]
    oidc_client_id = os.environ["OIDC_CLIENT_ID"]
    oidc_client_secret = os.environ["OIDC_CLIENT_SECRET"]
    cookie_secret = os.environ["RSPY_COOKIE_SECRET"]

    # Existing middlewares
    middleware_names = [middleware.cls.__name__ for middleware in app.user_middleware]

    # If not already there, add the SessionMiddleware, used to save session cookies.
    # Add it at the end (after the CORS middleware, that must be first)
    # Code copy/pasted from app.add_middleware(SessionMiddleware, secret_key=cookie_secret)
    if "SessionMiddleware" not in middleware_names:
        if app.middleware_stack is not None:
            raise RuntimeError("Cannot add middleware after an application has started")
        app.user_middleware.append(Middleware(SessionMiddleware, secret_key=cookie_secret))

    # Configure the oauth2 authentication

    domain_url = f"{oidc_endpoint}/realms/{oidc_realm}"
    config_data = {
        "KEYCLOAK_CLIENT_ID": oidc_client_id,
        "KEYCLOAK_CLIENT_SECRET": oidc_client_secret,
        "KEYCLOAK_DOMAIN_URL": domain_url,
    }
    config = StarletteConfig(environ=config_data)
    oauth = starlette_client.OAuth(config)

    oidc_metadata_url = domain_url + "/.well-known/openid-configuration"

    global KEYCLOAK
    KEYCLOAK = oauth.register(
        "keycloak",
        client_id=oidc_client_id,
        client_secret=oidc_client_secret,
        server_metadata_url=oidc_metadata_url,
        client_kwargs={
            "code_challenge_method": "S256",  # Add PKCE for Authorization Code
            "scope": "openid profile email",
        },
    )

    @app.exception_handler(LoginAndRedirect)
    async def login_and_redirect(request: Request, exc: LoginAndRedirect) -> Response:
        """Used to call the login endpoint and redirect to the calling endpoint."""
        return await login(request)

    @router.get(LOGIN_FROM_BROWSER, include_in_schema=False)
    async def login_from_browser(request: Request):
        """Login to oauth2 from a browser"""
        return await login(request)

    @router.get(LOGIN_FROM_CONSOLE, include_in_schema=False)
    async def login_from_console(request: Request):
        """Login to oauth2 from a python console"""
        return await login(request)

    @router.get("/console_logged_message", include_in_schema=False)
    async def console_logged_message_endpoint() -> HTMLResponse:
        """Send message to the user when they are already logged in from the python console."""
        return await console_logged_message()

    @router.get("/me")
    async def show_my_information(auth_info: Annotated[AuthInfo, Depends(get_user_info)]):
        """Show user information."""
        return {
            "user_login": auth_info.user_login,
            "iam_roles": auth_info.iam_roles,
        }

    @router.get("/logout", include_in_schema=False)
    async def logout(request: Request):
        """Logout the user."""

        # Remove the cookie
        request.session.pop(COOKIE_NAME, None)

        # Clear the state values used by the oauth2 authentication process
        for key in list(request.session.keys()):
            if key.startswith("_state_"):
                request.session.pop(key, None)

        metadata = await KEYCLOAK.load_server_metadata()
        end_session_endpoint = metadata["end_session_endpoint"]

        return HTMLResponse(
            "You are logged out.<br><br>"
            "Click here to also log out from the authentication server: "
            f"<a href='{end_session_endpoint}' target='_blank'>"
            f"{end_session_endpoint}</a>",
        )

    return router


# Utility class to get user information from the KeyCloak server
if settings.CLUSTER_MODE:
    kcutil = KCUtil()


async def get_user_info(request: Request) -> AuthInfo:
    """
    Get user information from the OAuth2 authentication and the KeyCloak server.

    Args:
        request (Request): HTTP request
        is_endpoint_dependency (bool): is this function called as an endpoint dependency ?

    Returns:
        tuple: A tuple containing user IAM roles, configuration data, and user login information.
    """

    # Read user information from cookies to see if he's logged in
    user = request.session.get(COOKIE_NAME)
    if not user:
        # We can login then redirect to this endpoint, but this is not possible to make redirection from the Swagger.
        # In this case, referer = http://<domain>:<port>/docs
        referer = request.headers.get("referer")
        if referer and (urlparse(referer).path.rstrip("/") == SWAGGER_HOMEPAGE):

            # login_url = request.url_for("login_from_browser") # doesn't work for all endpoints
            login_url = f"{str(request.base_url).rstrip('/')}{AUTH_PREFIX}{LOGIN_FROM_BROWSER}"

            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"You must first login by calling this URL in your browser: {login_url}",
            )

        # Login and redirect to the calling endpoint.
        # Let's hope that the caller called from a browser (can we detect this ?) and not a python console
        # or the redirections won't work.
        raise LoginAndRedirect

    # Read the user ID and name from the cookie = from the OAuth2 authentication process
    user_id = user.get("sub")
    user_login = user.get("preferred_username")

    # Now call the KeyCloak server again to get the user information (IAM roles, ...) from the user ID
    user_info = kcutil.get_user_info(user_id)

    # If the user is still enabled in KeyCloak
    if user_info.is_enabled:

        # The configuration dict is only set with the API key, not with the OAuth2 authentication.
        return AuthInfo(user_login=user_login, iam_roles=user_info.roles, apikey_config={})

    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User {user_login!r} not found in keycloak.",
        )
