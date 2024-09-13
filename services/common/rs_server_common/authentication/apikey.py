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
API key authentication functions implementation.

Note: calls https://github.com/csgroup-oss/apikey-manager
"""

import sys
import traceback
from os import environ as env
from typing import Annotated

import httpx
from asyncache import cached
from cachetools import TTLCache
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from rs_server_common import settings
from rs_server_common.utils.logging import Logging

# from functools import wraps
from rs_server_common.utils.utils2 import AuthInfo, read_response_error
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_500_INTERNAL_SERVER_ERROR

logger = Logging.default(__name__)

# HTTP header field for the api key
APIKEY_HEADER = "x-api-key"

APIKEY_SCHEME_NAME = "You can also authenticate with an API key"

# Just print the plain RSPY_UAC_HOMEPAGE environment variable name.
# When the rs-server-frontend container will start, it will replace it with its associated value.
APIKEY_DESCRIPTION = """
<h3><a href="${RSPY_UAC_HOMEPAGE}" target="_blank">Create it from here</a></h3>

<h3><a href="https://home.rs-python.eu/rs-documentation/rs-server/docs/doc/users/oauth2_apikey_manager" target="_blank">
See the documentation</a></h3>
"""

# API key authentication using a header
APIKEY_AUTH_HEADER = APIKeyHeader(
    name=APIKEY_HEADER,
    scheme_name=APIKEY_SCHEME_NAME,
    auto_error=False,
    description=APIKEY_DESCRIPTION,
)


async def apikey_security(
    apikey_value: Annotated[str, Security(APIKEY_AUTH_HEADER)] = "",
) -> AuthInfo | None:
    """
    Check the api key validity, passed as an HTTP header.

    Args:
        apikey_value (Security): API key passed in HTTP header

    Returns:
        Authentication information from the keycloak account, associated to the api key.
        Or None if no api key is provided.
    """

    if not apikey_value:
        return None

    # Call the cached function (fastapi Depends doesn't work with @cached)
    ret = await __apikey_security_cached(str(apikey_value))
    logger.debug(f"API key information: {ret}")
    return ret


# The following variable is needed for the tests to pass
ttl_cache: TTLCache = TTLCache(maxsize=sys.maxsize, ttl=120)


@cached(cache=ttl_cache)
async def __apikey_security_cached(apikey_value) -> AuthInfo:
    """
    Cached version of apikey_security. Cache an infinite (sys.maxsize) number of results for 120 seconds.

    This function serves as a cached version of apikey_security. It retrieves user access control information
    from the User Authentication and Authorization Control (UAC) manager and caches the result for performance
    optimization.

    Args:
        apikey_value (str): The API key value.

    Returns:
        AuthInfo: Authentication information from the keycloak account, associated to the api key.

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
        return AuthInfo(
            user_login=contents["user_login"],
            iam_roles=contents["iam_roles"],
            apikey_config=contents["config"],
        )

    # Forward error
    raise HTTPException(response.status_code, f"UAC manager: {read_response_error(response)}")
