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
from fastapi.security import APIKeyHeader, APIKeyQuery
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
APIKEY_QUERY = "api-key"

# API key authentication using a header and a query parameter.
APIKEY_AUTH_HEADER = APIKeyHeader(name=APIKEY_HEADER, scheme_name="API key passed by HTTP headers", auto_error=False)
APIKEY_AUTH_QUERY = APIKeyQuery(
    name=APIKEY_QUERY,
    scheme_name="API key passed by URL query parameter",
    auto_error=False,
)

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
    apikey_query: Annotated[str, Security(APIKEY_AUTH_QUERY)],
) -> tuple[list, dict, str]:
    """
    FastAPI Security dependency for the cluster mode. Check the api key validity, passed as an HTTP header.

    Args:
        apikey_header (Security): API key passed by HTTP headers
        apikey_query (Security): API key passed by URL query parameter

    Returns:
        Tuple of (IAM roles, config) information from the keycloak server, associated with the api key.
    """

    # Use the api key passed by either http headers or query parameter
    apikey_value = apikey_header or apikey_query
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
async def __apikey_security_cached(apikey_value) -> tuple[list, dict, dict]:
    """
    Cached version of apikey_security. Cache an infinite (sys.maxsize) number of results for 120 seconds.
    """
    # The uac manager check url is passed as an environment variable
    try:
        check_url = env["RSPY_UAC_CHECK_URL"]
    except KeyError:
        raise HTTPException(HTTP_400_BAD_REQUEST, "UAC manager URL is undefined")  # pylint: disable=raise-missing-from

    # Request the uac, pass user-defined api key by http headers
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
        station (str): The station name = adgs or cadip
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
