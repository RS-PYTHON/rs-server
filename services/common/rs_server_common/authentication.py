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

Note: calls https://gitlab.si.c-s.fr/space_applications/eoservices/apikey-manager
"""

import sys
import traceback
from functools import wraps
from os import environ as env
from typing import Annotated

import httpx
from asyncache import cached
from cachetools import TTLCache
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from rs_server_common import settings
from rs_server_common.utils.logging import Logging

# from functools import wraps
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

logger = Logging.default(__name__)

# HTTP header and query parameter fields for the api key
APIKEY_HEADER = "x-api-key"
# APIKEY_QUERY = "api-key" # disabled for now

# Just print the plain RSPY_UAC_HOMEPAGE environment variable name.
# When the rs-server-frontend container will start, it will replace it with its associated value.
APIKEY_DESCRIPTION = """
<h3><a href="${RSPY_UAC_HOMEPAGE}">Create it from here</a></h3>

<h3><a href="https://home.rs-python.eu/rs-documentation/rs-server/docs/doc/users/oauth2_apikey_manager">
See the documentation</a></h3>
"""

# API key authentication using a header and a query parameter (disabled for now)
APIKEY_AUTH_HEADER = APIKeyHeader(
    name=APIKEY_HEADER,
    scheme_name="You need an API key to use these endpoints",
    auto_error=False,
    description=APIKEY_DESCRIPTION,
)
# APIKEY_AUTH_QUERY = APIKeyQuery(
#     name=APIKEY_QUERY, scheme_name="API key passed in URL query parameter", auto_error=False)

# Look up table for stations
STATIONS_AUTH_LUT = {
    "adgs": "adgs",
    "ins": "cadip_ins",
    "mps": "cadip_mps",
    "mti": "cadip_mti",
    "nsg": "cadip_nsg",
    "sgs": "cadip_sgs",
    "cadip": "cadip_cadip",
}


async def apikey_security(
    request: Request,
    apikey_header: Annotated[str, Security(APIKEY_AUTH_HEADER)],
    # apikey_query: Annotated[str, Security(APIKEY_AUTH_QUERY)],
) -> tuple[list[str], dict, str]:
    """
    FastAPI Security dependency for the cluster mode. Check the api key validity, passed as an HTTP header.

    Args:
        apikey_header (Security): API key passed in HTTP header

    Returns:
        Tuple of (IAM roles, config, user login) information from the keycloak account, associated to the api key.
    """

    # Use the api key passed by either http headers or query parameter (disabled for now)
    apikey_value = apikey_header  # or apikey_query
    if not apikey_value:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Not authenticated",
        )

    # Call the cached function (fastapi Depends doesn't work with @cached)
    auth_roles, auth_config, user_login = await __apikey_security_cached(str(apikey_value))
    request.state.auth_roles = auth_roles
    request.state.auth_config = auth_config
    request.state.user_login = user_login
    logger.debug(f"API key information: {auth_roles, auth_config, user_login}")
    return auth_roles, auth_config, user_login


# The following variable is needed for the tests to pass
ttl_cache: TTLCache = TTLCache(maxsize=sys.maxsize, ttl=120)


@cached(cache=ttl_cache)
async def __apikey_security_cached(apikey_value) -> tuple[list[str], dict, str]:
    """
    Cached version of apikey_security. Cache an infinite (sys.maxsize) number of results for 120 seconds.

    This function serves as a cached version of apikey_security. It retrieves user access control information
    from the User Authentication and Authorization Control (UAC) manager and caches the result for performance
    optimization.

    Args:
        apikey_value (str): The API key value.

    Returns:
        tuple: A tuple containing user IAM roles, configuration data, and user login information.

    Raises:
        HTTPException: If there is an error connecting to the UAC manager or if the UAC manager returns an error.
    """

    # The uac manager check url is passed as an environment variable
    try:
        check_url = env["RSPY_UAC_CHECK_URL"]
    except KeyError:
        raise HTTPException(HTTP_400_BAD_REQUEST, "UAC manager URL is undefined")  # pylint: disable=raise-missing-from

    # Request the uac, pass user-defined api key in http header
    try:
        response = await settings.http_client().get(check_url, headers={APIKEY_HEADER: apikey_value or ""})
    except httpx.HTTPError as error:
        message = "Error connecting to the UAC manager"
        logger.error(f"{message}\n{traceback.format_exc()}")
        raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, message) from error

    # Read the api key info
    if response.is_success:
        contents = response.json()
        # Note: for now, config is an empty dict
        return contents["iam_roles"], contents["config"], contents["user_login"]

    # Try to read the response detail or error
    try:
        json = response.json()
        if "detail" in json:
            detail = json["detail"]
        else:
            detail = json["error"]

    # If this fail, get the full response content
    except Exception:  # pylint: disable=broad-exception-caught
        detail = response.read().decode("utf-8")

    # Forward error
    raise HTTPException(response.status_code, f"UAC manager: {detail}")


def apikey_validator(station, access_type):
    """Decorator to validate API key access for a specific station and access type.

    This decorator checks if the authorization key contains the necessary role to access
    the specified station with the specified access type.

    Args:
        station (str): The name of the station, either "adgs" or "cadip".
        access_type (str): The type of access, such as "download" or "read".

    Raises:
        HTTPException: If the authorization key does not include the required role
            to access the specified station with the specified access type.

    Returns:
        function (Callable): The decorator function.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if settings.CLUSTER_MODE:
                # Read the full cadip station passed in parameter e.g. INS, MPS, ...
                if station == "cadip":
                    cadip_station = kwargs["station"]  # ins, mps, mti, nsg, sgs, or cadip
                    try:
                        full_station = STATIONS_AUTH_LUT[cadip_station.lower()]
                    except KeyError as exception:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Unknown CADIP station: {cadip_station!r}",
                        ) from exception
                else:  # for adgs
                    full_station = station

                requested_role = f"rs_{full_station}_{access_type}".upper()
                try:
                    auth_roles = [role.upper() for role in kwargs["request"].state.auth_roles]
                except KeyError:
                    auth_roles = []

                if requested_role not in auth_roles:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"Authorization key does not include the right role to {access_type} "
                        f"from the {full_station!r} station",
                    )

            return func(*args, **kwargs)

        return wrapper

    return decorator
