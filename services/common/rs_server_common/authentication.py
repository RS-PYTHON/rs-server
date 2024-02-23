"""Authentication functions implementation"""


#
# NOTE: taken from https://gitlab.si.c-s.fr/space_applications/eoservices/apikey-manager
#
# TODO: should we either only accept apikey in the http headers (not query) ?
# or also implement the middleware to capture the apikey from the url ? See:
# https://gitlab.si.c-s.fr/space_applications/eoservices/apikey-manager/-/blob/main/app/main.py#L75
#


from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, APIKeyQuery
from httpx import AsyncClient
from rs_server_common.depends import http_client
from starlette.status import HTTP_403_FORBIDDEN

api_key_query = APIKeyQuery(name="api-key", scheme_name="API key query", auto_error=False)
api_key_header = APIKeyHeader(name="x-api-key", scheme_name="API key header", auto_error=False)


async def api_key_security(
    query_param: Annotated[str, Security(api_key_query)],
    header_param: Annotated[str, Security(api_key_header)],
    client: AsyncClient = Depends(http_client),
):
    params = {"api-key", query_param} if query_param else {}
    headers = {"x-api-key": api_key_header} if header_param else {}
    return client.get("...", params=params, headers=headers)
    # if not query_param and not header_param:
    #     raise HTTPException(
    #         status_code=HTTP_403_FORBIDDEN,
    #         detail="An API key must be passed as query or header",
    #     )

    # key_info = apikey_crud.check_key(query_param or header_param)

    # if key_info:
    #     return key_info
    # else:
    #     raise HTTPException(
    #         status_code=HTTP_403_FORBIDDEN, detail="Wrong, revoked, or expired API key."
    #     )
