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

"""
Authentication functions implementation.
"""

import os
from contextlib import suppress
from typing import Annotated, Literal

import jwt
import requests
from cachetools import TTLCache
from cachetools_async import cached
from fastapi import HTTPException, Request, Security, status
from rs_server_common import settings
from rs_server_common.authentication import oauth2
from rs_server_common.authentication.apikey import (
    APIKEY_AUTH_HEADER,
    APIKEY_HEADER,
    apikey_security,
)
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import AuthInfo, S3Credentials, read_response_error
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import HTTPConnection

logger = Logging.default(__name__)

# Mocker doesn't work on the authenticate function that is a FastAPI dependency,
# I don't know why, so just use this hack to spy the function from the pytests.
FROM_PYTEST = False


def authenticate_from_pytest(auth_info: AuthInfo) -> AuthInfo:
    """'authenticate' function called from pytest."""
    return auth_info


@cached(cache=TTLCache(maxsize=1, ttl=24 * 3600))  # cache the results for n seconds, they should not change often
async def get_issuer_and_public_key() -> tuple[str, str]:
    """Get issuer URL from OIDC environment, and public key from the issuer."""

    # Read environment variables
    oidc_endpoint = os.environ["OIDC_ENDPOINT"]
    oidc_realm = os.environ["OIDC_REALM"]
    oidc_metadata_url = f"{oidc_endpoint}/realms/{oidc_realm}/.well-known/openid-configuration"

    response = await settings.http_client().get(oidc_metadata_url)
    issuer = response.json()["issuer"]
    response = await settings.http_client().get(issuer)
    public_key = response.json()["public_key"]

    key = "-----BEGIN PUBLIC KEY-----\n" + public_key + "\n-----END PUBLIC KEY-----"
    return (issuer, key)


async def authenticate(
    request: Request,
    apikey_value: Annotated[str, Security(APIKEY_AUTH_HEADER)] = "",
) -> AuthInfo:
    """
    FastAPI Security dependency for the cluster mode. Check the api key validity, passed as an HTTP header,
    or that the user is authenticated with oauth2 (keycloak).

    Args:
        request (Request): Incoming HTTP request, used to detect STAC Browser origin and forward authentication context.
        apikey_value (Security): API key passed in HTTP header

    Returns:
        Tuple of (IAM roles, config, user login) information from the keycloak account, associated to the api key
        or the user oauth2 account.
    """

    # If the request comes from the stac browser
    if settings.request_from_stacbrowser(request):

        # With the stac browser, we don't use either api key or oauth2.
        # It passes an authorization token in a specific header.
        if token := request.headers.get("authorization"):
            issuer, key = await get_issuer_and_public_key()
            if token.startswith("Bearer "):
                token = token[7:]  # remove the "Bearer " header

            # Decode the token
            userinfo = jwt.decode(
                token,
                key=key,
                issuer=issuer,
                audience=os.environ["OIDC_CLIENT_ID"],
                algorithms=["RS256"],
            )

            # The result contains the auth roles we need, but still get them from keycloak
            # so we are sure to have the same behaviour than with the apikey and oauth2
            kc_info = oauth2.KCUTIL.get_user_info(userinfo.get("sub"))

            user_login = userinfo.get("preferred_username")
            if not kc_info.is_enabled:
                raise HTTPException(
                    # Don't use 401 or the stac browser will try to connect to this endpoint again and this will loop
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User {user_login!r} is disabled from KeyCloak.",
                )
            auth_info = AuthInfo(user_login=user_login, iam_roles=kc_info.roles, attributes=kc_info.attributes)

        else:
            # Else, return an "unauthorized" error to force the browser to authenticate
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication needed from the STAC browser",
            )

    # Not from the stac browser
    else:
        # Try to authenticate with the api key value
        auth_info = await apikey_security(apikey_value)

        # Else try to authenticate with oauth2
        if not auth_info:
            try:
                auth_info = await oauth2.get_user_info(request)
            # Update error message returned by the oauth2 module
            except StarletteHTTPException as exc:
                exc.detail = f"Missing API key and OAuth2 token ({exc.args[1]})"
                exc.args = (*exc.args[0:1], exc.detail, *exc.args[2:])
                raise

    # Save information in the request state and return it
    request.state.user_login = auth_info.user_login
    request.state.auth_roles = auth_info.iam_roles
    request.state.auth_attributes = auth_info.attributes
    return authenticate_from_pytest(auth_info) if FROM_PYTEST else auth_info


def auth_validation(
    station_type: Literal["auxip", "cadip", "prip", "lta"],
    access_type: Literal["landing_page", "read", "execute", "staging_download", "dismiss"],
    request: Request,
    station: str = "",
    staging_process: bool = False,
):
    """
    Authorization validation: check that the user has the right role for a specific action.

    Args:
        station_type: either auxip, cadip, ...
        access_type: either landing_page, read, ...
        request: HTTP request
        station: specific adgs station (adgs or adgs2) or cadip station (ins, mps, ...) or prip or lta station
        staging_process: specific case for the staging

    Raises:
        HTTPException if the user does not have the right role.
    """

    # In local mode, there is no authorization to check
    if settings.LOCAL_MODE:
        return

    if staging_process:
        requested_role = f"rs_processes_{access_type}_{station_type}"
    elif access_type == "landing_page":
        requested_role = f"rs_{station_type}_landing_page"
    else:
        requested_role = f"rs_{station_type}_{station}_{access_type}".lower()

    requested_role = requested_role.lower()
    logger.debug(f"Requested role: {requested_role!r}")

    try:
        auth_roles = [role.lower() for role in request.state.auth_roles]
        user_login = request.state.user_login
    except AttributeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authorization information is missing",
        ) from exc

    if requested_role not in auth_roles:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing authorization role {requested_role!r} for user {user_login!r} with roles: {auth_roles}",
        )


def get_s3_credentials(request: Request) -> S3Credentials:
    """
    Return the S3 object storage credentials for the logged user.
    These credentials are returned by the OSAM service.
    """
    # Try to return the S3 credentials already calculated for this request (and thus for this logged user)
    with suppress(AttributeError):
        return request.state.s3_credentials

    # Else we're calculating it.
    # We create a new HTTP request to OSAM to retrieve the S3 credentials of the user.
    # The user is already logged in, this is why he's able to call the current request.
    # The current request contains the user credentials in its api key and/or oauth2 cookie.
    # So we copy the api key and oauth2 cookie to the new request so the user will also be authenticated in osam.
    osam_request = requests.Session()

    # Copy the api key from the request headers
    apikey_value = request.headers.get(APIKEY_HEADER)

    # Copy the "session" cookie from the request, as in starlette/middleware/sessions.py::__call__
    connection = HTTPConnection(request.scope)
    if session_cookie := connection.cookies.get("session"):
        osam_request.cookies.set("session", session_cookie)

    # Send request to osam and check result.
    # NOTE: the results are cached on the osam server-side for every user, so it's calculated only once.
    osam_response = osam_request.get(
        os.environ["RSPY_HOST_OSAM"] + "/storage/account/credentials",
        headers={APIKEY_HEADER: apikey_value} if apikey_value else {},
    )
    if not osam_response.ok:
        raise HTTPException(
            osam_response.status_code,
            f"Failed to get user credentials from OSAM: {read_response_error(osam_response)}",
        )

    # Read result from osam
    osam_credentials = osam_response.json()
    try:
        request.state.s3_credentials = S3Credentials(
            access_key_id=osam_credentials["access_key"],
            secret_access_key=osam_credentials["secret_key"],
            endpoint_url=osam_credentials["endpoint"],
            region_name=osam_credentials["region"],
        )
        return request.state.s3_credentials
    except KeyError as exc:
        # WARNING: print only the s3 credential keys in this error message, not the values !
        raise KeyError(f"Invalid credentials returned by OSAM: {list(osam_credentials.keys())}") from exc
