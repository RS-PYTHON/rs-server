"""Authentication functions implementation"""
#
# NOTE: taken from https://gitlab.si.c-s.fr/space_applications/eoservices/apikey-manager
#

from os import environ as env
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, APIKeyQuery
from httpx import AsyncClient
from rs_server_common.depends import http_client
from starlette.status import HTTP_400_BAD_REQUEST

QUERY_NAME = "api-key"
HEADER_NAME = "x-api-key"

api_key_query = APIKeyQuery(name=QUERY_NAME, scheme_name="API key passed as query parameter", auto_error=False)
api_key_header = APIKeyHeader(name=HEADER_NAME, scheme_name="API key passed in header", auto_error=False)


async def api_key_security(
    query_param: Annotated[str, Security(api_key_query)],
    header_param: Annotated[str, Security(api_key_header)],
    client: AsyncClient = Depends(http_client),
):
    # The uac manager check url is passed as an environment variable
    try:
        check_url = env["RSPY_UAC_CHECK_URL"]
    except KeyError:
        raise HTTPException(HTTP_400_BAD_REQUEST, "UAC manager URL is undefined")

    # Build the request parameters and header
    params = {QUERY_NAME: query_param} if query_param else {}
    headers = {HEADER_NAME: header_param} if header_param else {}

    # Request the uac, pass user-defined credentials
    response = await client.get(check_url, params=params, headers=headers)

    # Return the api key info as a json
    if response.is_success:
        return response.json()

    # Try to read the response detail
    try:
        detail = response.json()["detail"]

    # If this fail, get the full response content
    except Exception:
        detail = response.read().decode("utf-8")

    # Forward error
    raise HTTPException(response.status_code, detail)
