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
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

logger = Logging.default(__name__)

# HTTP header field for the api key
APIKEY_HEADER = "x-api-key"

# API key authentication using a header.
APIKEY_SECURITY = APIKeyHeader(name=APIKEY_HEADER, scheme_name="API key passed in HTTP header", auto_error=True)

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
    apikey_value: Annotated[str, Security(APIKEY_SECURITY)],
) -> tuple[list, dict, str]:
    """
    FastAPI Security dependency for the cluster mode. Check the api key validity, passed as an HTTP header.

    Args:
        apikey_value (Security): API key passed in header,

    Returns:
        Tuple of (IAM roles, config) information from the keycloak server, associated with the api key.
    """
    # Call the cached function (fastapi Depends doesn't work with @cached)
    auth_roles, auth_config, user_login = await __apikey_security_cached(str(apikey_value))
    request.state.auth_roles = auth_roles
    request.state.auth_config = auth_config
    return auth_roles, auth_config, user_login


# The following variable is needed for the tests to pass
ttl_cache: TTLCache = TTLCache(maxsize=sys.maxsize, ttl=120)


@cached(cache=ttl_cache)
async def __apikey_security_cached(apikey_value) -> tuple[list, dict, dict]:
    """
    Cached version of apikey_security. Cache an infinite (sys.maxsize) number of results for 120 seconds.
    """
    # The uac manager check url is passed as an environment variable
    try:
        check_url = env["RSPY_UAC_CHECK_URL"]
    except KeyError:
        raise HTTPException(HTTP_400_BAD_REQUEST, "UAC manager URL is undefined")  # pylint: disable=raise-missing-from

    # Request the uac, pass user-defined credentials
    try:
        response = await settings.http_client().get(check_url, headers={APIKEY_HEADER: apikey_value or ""})
    except httpx.HTTPError as error:
        message = "Error connecting to the UAC manager"
        logger.error(f"{message}\n{traceback.format_exc()}")
        raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, message) from error

    # Read the api key info
    if response.is_success:
        contents = response.json()
        str_roles, config, user_login = contents["iam_roles"], contents["config"], contents["user_login"]

        # Convert IAM roles to enum
        roles = []
        for role in str_roles:
            try:
                roles.append(role)
            except KeyError:
                logger.warning(f"Unknown IAM role: {role!r}")

        # Note: for now, config is an empty dict
        return roles, config, user_login

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
    """Decorator to validate API key access.

    Args:
        station (str): The station name.
        access_type (str): The type of access.

    Raises:
        HTTPException: If the authorization key does not include the right role
            to access the specified station.

    Returns:
        function: Decorator function.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if settings.cluster_mode():
                try:
                    __station = STATIONS_AUTH_LUT[kwargs["station"].lower()] if station == "cadip" else station
                    requested_role = f"rs_{__station}_{access_type}".upper()
                    auth_roles = [role.upper() for role in kwargs["request"].state.auth_roles]
                except KeyError:
                    requested_role = None

                if not requested_role or requested_role not in auth_roles:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"Authorization key does not include the right role to \
{access_type} the {__station!r} station",
                    )

            return func(*args, **kwargs)

        return wrapper

    return decorator
