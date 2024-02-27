"""
Authentication functions implementation.

Note: calls https://gitlab.si.c-s.fr/space_applications/eoservices/apikey-manager
"""

import sys
from os import environ as env
from typing import Annotated

import httpx
from cachetools import TTLCache, cached
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from httpx import AsyncClient
from rs_server_common.settings import local_mode
from starlette.status import HTTP_400_BAD_REQUEST

# HTTP header field for the api key
HEADER_NAME = "x-api-key"

# API key authentication using a header.
api_key_header = APIKeyHeader(name=HEADER_NAME, scheme_name="API key passed in header", auto_error=False)


async def api_key_security(
    header_param: Annotated[str, Security(api_key_header)],
) -> tuple[dict, dict]:
    """
    FastAPI Security dependency for the cluster mode. Check the api key validity, passed as an HTTP header.

    Args:
        header_param (Security): API key passed in header,

    Returns:
        Tuple of (IAM roles, config) information from the keycloak server.
    """
    # Call the cached function (fastapi Depends doesn't work with @cached)
    return __api_key_security_cached(str(header_param))


@cached(cache=TTLCache(maxsize=sys.maxsize, ttl=120))
def __api_key_security_cached(header_param):
    """
    Cached version of api_key_security. Cache an infinite (sys.maxsize) number of results for 120 seconds.
    """
    # The uac manager check url is passed as an environment variable
    try:
        check_url = env["RSPY_UAC_CHECK_URL"]
    except KeyError:
        raise HTTPException(HTTP_400_BAD_REQUEST, "UAC manager URL is undefined")

    # Request the uac, pass user-defined credentials
    response = httpx.get(check_url, headers={HEADER_NAME: header_param or ""})

    # Return the api key info
    if response.is_success:
        contents = response.json()
        return contents["iam_roles"], contents["config"]

    # Try to read the response detail or error
    try:
        json = response.json()
        if "detail" in json:
            detail = json["detail"]
        else:
            detail = json["error"]

    # If this fail, get the full response content
    except Exception:
        detail = response.read().decode("utf-8")

    # Forward error
    raise HTTPException(response.status_code, detail)


# In local mode: no keycloak. Do nothing and return empty info.
# Redefine the api_key_security function so we don't have the lock icon anymore in the swagger.
if local_mode():
    api_key_security = lambda: ({}, {})
