"""
Authentication functions implementation.

Note: calls https://gitlab.si.c-s.fr/space_applications/eoservices/apikey-manager
"""

import sys
import traceback
from enum import Enum
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
STATIONS_AUTH_lut = {
    "adgs": "adgs",
    "ins": "cadip_ins",
    "mps": "cadip_mps",
    "mti": "cadip_nsg",
    "nsg": "cadip_nsg",
    "sgs": "cadip_sgs",
    "cadip": "cadip_cadip",
}


class Auth(Enum):
    """
    Enum values for authentication.

    NOTE: enum names = the values returned by keyclowk, uppercase
    """

    # IAM roles

    # ADGS
    RS_ADGS_READ = "rs_adgs_read"
    RS_ADGS_DOWNLOAD = "rs_adgs_download"

    # CADIP
    RS_CADIP_CADIP_READ = "rs_cadip_cadip_read"
    RS_CADIP_CADIP_DOWNLOAD = "rs_cadip_cadip_download"
    RS_CADIP_INS_READ = "rs_cadip_ins_read"
    RS_CADIP_INS_DOWNLOAD = "rs_cadip_ins_download"
    RS_CADIP_MPS_READ = "rs_cadip_mps_read"
    RS_CADIP_MPS_DOWNLOAD = "rs_cadip_mps_download"
    RS_CADIP_MTI_READ = "rs_cadip_mti_read"
    RS_CADIP_MTI_DOWNLOAD = "rs_cadip_mti_download"
    RS_CADIP_NSG_READ = "rs_cadip_nsg_read"
    RS_CADIP_NSG_DOWNLOAD = "rs_cadip_nsg_download"
    RS_CADIP_SGS_READ = "rs_cadip_sgs_read"
    RS_CADIP_SGS_DOWNLOAD = "rs_cadip_sgs_download"
    # TODO: above is cadip "cadip" station (does it really exist ?),
    # do the oter stations (ins, mps, ...) see stations_cfg.json ?

    # Catalog
    S1_ACCESS = "s1_access"  # TODO: use e.g. s1_read, s1_write, s1_download instead ?


async def apikey_security(
    request: Request,
    apikey_value: Annotated[str, Security(APIKEY_SECURITY)],
) -> tuple[list, dict]:
    """
    FastAPI Security dependency for the cluster mode. Check the api key validity, passed as an HTTP header.

    Args:
        apikey_value (Security): API key passed in header,

    Returns:
        Tuple of (IAM roles, config) information from the keycloak server, associated with the api key.
    """
    # Call the cached function (fastapi Depends doesn't work with @cached)
    auth_roles, auth_config = await __apikey_security_cached(str(apikey_value))
    request.state.auth_roles = auth_roles
    request.state.auth_config = auth_config
    return auth_roles, auth_config


@cached(cache=TTLCache(maxsize=sys.maxsize, ttl=120))
async def __apikey_security_cached(apikey_value) -> tuple[list, dict]:
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
        str_roles, config = contents["iam_roles"], contents["config"]

        # Convert IAM roles to enum
        roles = []
        for role in str_roles:
            try:
                roles.append(Auth[role.upper()])
            except KeyError:
                logger.warning(f"Unknown IAM role: {role!r}")

        # Note: for now, config is an empty dict
        return roles, config

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
    """Docstring to be added"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if settings.cluster_mode():
                try:
                    logger.info("Checking AUTH")
                    __station = STATIONS_AUTH_lut[kwargs["station"].lower()] if station == "cadip" else station
                    requested_role = Auth[f"rs_{__station}_{access_type}".upper()]
                    auth_roles = kwargs["request"].state.auth_roles
                    print(f"auth_roles = {auth_roles}")
                except KeyError:
                    requested_role = None

                if not requested_role or requested_role not in auth_roles:
                    logger.info("AUTH: Raising exception !")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail=f"Authorization key does not include the right role to \
{access_type} the {__station} station",
                    )
                logger.info("AUTH: PASS !")

            return func(*args, **kwargs)

        return wrapper

    return decorator


# def apikey_validator(station: str, access_type: str, request: Request):
#     """Docstring to be added"""
#     if not settings.cluster_mode():
#         return

#     try:
#         requested_role = Auth[f"rs_{station}_{access_type}".upper()]
#         auth_roles = request.state.auth_roles
#         logger.debug(
#             f"API key information for station: auth_roles = {auth_roles} | auth_config = {request.state.auth_config}",
#         )
#     except (KeyError, AttributeError):
#         requested_role = None
#         auth_roles = None
#     import pdb
#     pdb.set_trace
#     if not requested_role or not auth_roles or requested_role not in auth_roles:
#         raise HTTPException(
#             status_code=status.HTTP_401_UNAUTHORIZED,
#             detail=f"Authorization key does not include the right role to \
#                                      {access_type} the {station} station",
#         )
