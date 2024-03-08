"""
Authentication functions implementation.

Note: calls https://gitlab.si.c-s.fr/space_applications/eoservices/apikey-manager
"""

import sys
import traceback
from os import environ as env
from typing import Annotated

import httpx
from cachetools import TTLCache, cached
from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from rs_server_common.utils.logging import Logging
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

logger = Logging.default(__name__)

# HTTP header field for the api key
HEADER_NAME = "x-api-key"

# API key authentication using a header.
apikey_header = APIKeyHeader(name=HEADER_NAME, scheme_name="API key passed in HTTP header", auto_error=True)


async def apikey_security(
    request: Request,
    apikey_value: Annotated[str, Security(apikey_header)],
) -> tuple[dict, dict]:
    """
    FastAPI Security dependency for the cluster mode. Check the api key validity, passed as an HTTP header.

    Args:
        apikey_value (Security): API key passed in header,

    Returns:
        Tuple of (IAM roles, config) information from the keycloak server, associated with the api key.
    """
    # Call the cached function (fastapi Depends doesn't work with @cached)
    apikey_info = __apikey_security_cached(str(apikey_value))
    request.state.apikey_info = apikey_info
    return apikey_info


@cached(cache=TTLCache(maxsize=sys.maxsize, ttl=120))
def __apikey_security_cached(apikey_value):
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
        response = httpx.get(check_url, headers={HEADER_NAME: apikey_value or ""})
    except httpx.HTTPError as error:
        message = "Error connecting to the UAC manager"
        logger.error(f"{message}\n{traceback.format_exc()}")
        raise HTTPException(HTTP_500_INTERNAL_SERVER_ERROR, message) from error

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
    except Exception:  # pylint: disable=broad-exception-caught
        detail = response.read().decode("utf-8")

    # Forward error
    raise HTTPException(response.status_code, f"UAC manager: {detail}")
