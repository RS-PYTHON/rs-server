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

"""
Authentication functions implementation.
"""

from functools import wraps
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from rs_server_common import settings
from rs_server_common.authentication.apikey import APIKEY_AUTH_HEADER, apikey_security
from rs_server_common.authentication.oauth2 import get_user_info
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import AuthInfo

logger = Logging.default(__name__)

# Mocker doesn't work on the authenticate function that is a FastAPI dependency,
# I don't know why, so just use this hack to spy the function from the pytests.
FROM_PYTEST = False


def authenticate_from_pytest(auth_info: AuthInfo) -> AuthInfo:
    """'authenticate' function called from pytest."""
    return auth_info


async def authenticate(
    request: Request,
    apikey_value: Annotated[str, Security(APIKEY_AUTH_HEADER)] = "",
) -> AuthInfo:
    """
    FastAPI Security dependency for the cluster mode. Check the api key validity, passed as an HTTP header,
    or that the user is authenticated with oauth2 (keycloak).

    Args:
        apikey_value (Security): API key passed in HTTP header

    Returns:
        Tuple of (IAM roles, config, user login) information from the keycloak account, associated to the api key
        or the user oauth2 account.
    """

    # Try to authenticate with the api key value
    auth_info = await apikey_security(apikey_value)

    # Else try to authenticate with oauth2
    if not auth_info:
        auth_info = await get_user_info(request)

    if not auth_info:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # Save information in the request state and return it
    request.state.auth_roles = auth_info.iam_roles
    request.state.auth_config = auth_info.apikey_config
    request.state.user_login = auth_info.user_login
    return authenticate_from_pytest(auth_info) if FROM_PYTEST else auth_info


def auth_validator(station, access_type):
    """Decorator to validate API key access or oauth2 authentication (keycloak) for a specific station and access type.

    This decorator checks if the authorization contains the necessary role to access
    the specified station with the specified access type.

    Args:
        station (str): The name of the station, either "adgs" or "cadip".
        access_type (str): The type of access, such as "download" or "read".

    Raises:
        HTTPException: If the authorization does not include the required role
            to access the specified station with the specified access type.

    Returns:
        function (Callable): The decorator function.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            auth_validation(station, access_type, *args, **kwargs)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def auth_validation(station_type, access_type, *args, **kwargs):  # pylint: disable=unused-argument
    """Function called by auth_validator"""

    # In local mode, there is no authentication to check
    if settings.LOCAL_MODE:
        return

    # Read the full cadip station passed in parameter: ins, mps, mti, nsg, sgs, or cadip
    # No validation needed for landing pages.
    if station_type == "cadip" and access_type != "landing_page":
        full_station = "cadip_" + kwargs["station"]
    else:
        full_station = station_type

    requested_role = f"rs_{full_station}_{access_type}".upper()
    logger.debug(f"Requested role: {requested_role}")
    try:
        auth_roles = [role.upper() for role in kwargs["request"].state.auth_roles]
    except KeyError:
        auth_roles = []
    logger.debug(f"Auth roles: {auth_roles}")
    if requested_role not in auth_roles:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authorization does not include the right role to {access_type} "
            f"from the {full_station!r} station",
        )
