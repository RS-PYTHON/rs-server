# Copyright 2023-2025 Airbus, CS Group
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

"""Common functions for fastapi middlewares"""

import json
import traceback
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, ParamSpec, TypedDict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import brotli
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from rs_server_common import settings as common_settings
from rs_server_common.authentication import authentication, oauth2
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.authentication.oauth2 import LoginAndRedirect
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import read_streaming_response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware, _MiddlewareFactory
from starlette.middleware.base import BaseHTTPMiddleware

REL_TITLES = {
    "collection": "Collection",
    "item": "Item",
    "parent": "Parent Catalog",
    "root": "STAC Root Catalog",
    "conformance": "Conformance link",
    "service-desc": "Service description",
    "service-doc": "Service documentation",
    "search": "Search endpoint",
    "data": "Data link",
    "items": "This collection items",
    "self": "This collection",
    "license": "License description",
    "describedby": "Described by link",
    "next": "Next link",
    "previous": "Previous link",
}
# pylint: disable = too-few-public-methods, too-many-return-statements
logger = Logging.default(__name__)
P = ParamSpec("P")


class StacErrorResponse(TypedDict):
    """A JSON error response returned by the API, compliant with the STAC specification.

    The STAC API spec expects that `code` and `description` are both present in
    the payload.

    Attributes:
        code: A code representing the error, semantics are up to implementor.
        description: A description of the error.
    """

    code: str
    description: str


class Rfc7807ErrorResponse(TypedDict):
    """A JSON error response returned by the API, compliant with the RFC 7807 specification.

    Attributes:
        type: https://developer.mozilla.org/en/docs/Web/HTTP/Reference/Status/{status_code}
        status: HTTP response status code
        detail: A description of the error.
    """

    type: str
    status: int
    detail: str


class AuthenticationMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """
    Implement authentication verification.
    """

    def __init__(self, app, must_be_authenticated, dispatch=None):
        self.must_be_authenticated = must_be_authenticated
        super().__init__(app, dispatch)

    async def dispatch(self, request: Request, call_next: Callable):
        """
        Middleware implementation.
        """

        if common_settings.CLUSTER_MODE and self.must_be_authenticated(request.url.path):
            try:
                # Check the api key validity, passed in HTTP header, or oauth2 autentication (keycloak)
                await authentication.authenticate(
                    request=request,
                    apikey_value=request.headers.get(APIKEY_HEADER, None),
                )

            # Login and redirect to the calling endpoint.
            except LoginAndRedirect:
                return await oauth2.login(request)

        # Call the next middleware
        return await call_next(request)


class HandleExceptionsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to catch all exceptions and return a JSONResponse instead of raising them.
    This is useful in FastAPI when HttpExceptions are raised within the code but need to be handled gracefully.

    Attributes:
        rfc7807 (bool): If true, the returned content is compliant with RFC 7807. This is used by pygeoapi/ogc services.
        False by default = compliant to Stac specifications.
    """

    def __init__(self, app, rfc7807: bool = False, dispatch=None):
        """Constructor"""
        self.rfc7807: bool = rfc7807
        super().__init__(app, dispatch)

    @staticmethod
    def disable_default_exception_handler(app: FastAPI):
        """
        Disable the default FastAPI exception handler for HTTPException and StarletteHTTPException.
        We just re-raise the exceptions so they'll be handled by HandleExceptionsMiddleware.
        """

        @app.exception_handler(HTTPException)
        @app.exception_handler(StarletteHTTPException)
        async def exception_handler(_request: Request, _exc: HTTPException):
            """Implement disable_default_exception_handler"""
            # Note: we could raise(_exc) but it would increase the stack trace length with this module info.
            # We can just call raise because this function is called from an except clause.
            raise  # pylint: disable=misplaced-bare-raise

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            # Call next middleware, get and return response, handle errors
            response = await call_next(request)
            return await self.handle_errors(response)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            return await self.handle_exceptions(request, exc)

    @staticmethod
    def format_code(status_code: int) -> str:
        """Convert e.g. HTTP_500_INTERNAL_SERVER_ERROR into 'InternalServerError'"""
        phrase = HTTPStatus(status_code).phrase
        return "".join(word.title() for word in phrase.split())

    @staticmethod
    def rfc7807_response(status_code: int, detail: str) -> Rfc7807ErrorResponse:
        """Return Rfc7807ErrorResponse instance"""
        return Rfc7807ErrorResponse(
            type=f"https://developer.mozilla.org/en/docs/Web/HTTP/Reference/Status/{status_code}",
            status=status_code,
            detail=detail,
        )

    async def handle_errors(self, response: StreamingResponse) -> Response:
        """
        If no errors, just return the original response.
        In case of errors, log, format and return the response contents.
        """
        if not 400 <= response.status_code < 600:
            return response  # no error, return the original response

        # Read response content
        try:
            content = await read_streaming_response(response)

        # If we fail to read content, just return the original response
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(exc)
            return response

        # The content should be formated as a XxxErrorResponse
        formatted: Rfc7807ErrorResponse | StacErrorResponse | None = None
        try:
            if self.rfc7807:
                formatted = Rfc7807ErrorResponse(
                    type=str(content["type"]),
                    status=int(content["status"]),
                    detail=str(content["detail"]),
                )
            else:
                formatted = StacErrorResponse(code=str(content["code"]), description=str(content["description"]))
            if formatted != content:
                formatted = None
        except Exception:  # pylint: disable=broad-exception-caught   # nosec B110
            pass

        # Else format the content
        if not formatted:
            description = json.dumps(content) if isinstance(content, (dict, list, set)) else str(content)
            if self.rfc7807:
                formatted = self.rfc7807_response(response.status_code, detail=description)
            else:
                formatted = StacErrorResponse(code=self.format_code(response.status_code), description=description)

        logger.error(f"{response.status_code}: {json.dumps(formatted)}")
        return JSONResponse(status_code=response.status_code, content=formatted)

    async def handle_exceptions(self, request: Request, exc: Exception) -> JSONResponse:
        """In case of exceptions, log the response contents"""

        # Log current stack trace
        logger.exception(exc)

        # Calculate HTTP response status code (int) and StacErrorResponse code (str) and description (str)
        if isinstance(exc, StarletteHTTPException):  # applies to HTTPException and StarletteHTTPException
            status_code = exc.status_code
            # Format int status code into str
            str_code = self.format_code(exc.status_code)
            description = str(exc.detail)

        else:
            # Use generic 400 or 500 code
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if HandleExceptionsMiddleware.is_bad_request(request, exc)
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            str_code = exc.__class__.__name__
            description = str(exc)

        error_response: Rfc7807ErrorResponse | StacErrorResponse
        if self.rfc7807:
            error_response = self.rfc7807_response(status_code, detail=description)
        else:
            error_response = StacErrorResponse(code=str_code, description=description)
        return JSONResponse(status_code=status_code, content=error_response)

    @staticmethod
    def is_bad_request(request: Request, e: Exception) -> bool:
        """
        Determines if the request that raised this exception shall be considered as a bad request
        and return a 400 error code.

        This function can be overriden by the caller if needed with:
        HandleExceptionsMiddleware.is_bad_request = my_callable
        """
        return "bbox" in request.query_params and (
            str(e).endswith(" must have 4 or 6 values.") or str(e).startswith("could not convert string to float: ")
        )


class PaginationLinksMiddleware(BaseHTTPMiddleware):
    """
    Middleware to implement 'first' button's functionality in STAC Browser
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ):  # pylint: disable=too-many-branches,too-many-statements

        # Only for /search in auxip, prip, cadip
        if request.url.path in ["/auxip/search", "/cadip/search", "/prip/search", "/catalog/search"]:

            first_link: dict[str, Any] = {
                "rel": "first",
                "type": "application/geo+json",
                "method": request.method,
                "href": f"{str(request.base_url).rstrip('/')}{request.url.path}",
                "title": "First link",
            }

            if common_settings.CLUSTER_MODE:
                first_link["href"] = f"https://{str(request.base_url.hostname).rstrip('/')}{request.url.path}"

            if request.method == "GET":
                # parse query params to remove any 'prev' or 'next'
                query_dict = dict(request.query_params)

                query_dict.pop("token", None)
                if "page" in query_dict:
                    query_dict["page"] = "1"
                new_query_string = urlencode(query_dict, doseq=True)
                first_link["href"] += f"?{new_query_string}"

            elif request.method == "POST":
                try:
                    query = await request.json()
                    body = {}

                    for key in ["datetime", "limit"]:
                        if key in query and query[key] is not None:
                            body[key] = query[key]

                    if "token" in query and request.url.path != "/catalog/search":
                        body["token"] = "page=1"  # nosec

                    first_link["body"] = body
                except Exception:  # pylint: disable = broad-exception-caught
                    logger.error(traceback.format_exc())

            response = await call_next(request)

            encoding = response.headers.get("content-encoding", "")
            if encoding == "br":
                body_bytes = b"".join([section async for section in response.body_iterator])
                response_body = brotli.decompress(body_bytes)

                if request.url.path == "/catalog/search":
                    first_link["auth:refs"] = ["apikey", "openid", "oauth2"]
            else:
                response_body = b""
                async for chunk in response.body_iterator:
                    response_body += chunk

            try:
                data = json.loads(response_body)

                links = data.get("links", [])
                has_prev = any(link.get("rel") == "previous" for link in links)

                if has_prev is True:
                    links.append(first_link)
                    data["links"] = links

                headers = dict(response.headers)
                headers.pop("content-length", None)

                if encoding == "br":
                    new_body = brotli.compress(json.dumps(data).encode("utf-8"))
                else:
                    new_body = json.dumps(data).encode("utf-8")

                response = Response(
                    content=new_body,
                    status_code=response.status_code,
                    headers=headers,
                    media_type="application/json",
                )
            except Exception:  # pylint: disable = broad-exception-caught
                headers = dict(response.headers)
                headers.pop("content-length", None)

                response = Response(
                    content=response_body,
                    status_code=response.status_code,
                    headers=headers,
                    media_type=response.headers.get("content-type"),
                )
        else:
            return await call_next(request)

        return response


def get_link_title(link: dict, entity: dict) -> str:
    """
    Determine a human-readable STAC link title based on the link relation and context.
    """
    rel = link.get("rel")
    href = link.get("href", "")
    if "title" in link:
        # don't overwrite
        return link["title"]
    match rel:
        # --- special cases needing entity context ---
        case "collection":
            return entity.get("title") or entity.get("id") or REL_TITLES["collection"]
        case "item":
            return entity.get("title") or entity.get("id") or REL_TITLES["item"]
        case "self" if entity.get("type") == "Catalog":
            return "STAC Landing Page"
        case "self" if href.endswith("/collections"):
            return "All Collections"
        case "child":
            path = urlparse(href).path
            collection_id = path.split("/")[-1] if path else "unknown"
            return f"All from collection {collection_id}"
        # --- all others: just lookup in REL_TITLES ---
        case _:
            return REL_TITLES.get(rel, href or "Unknown Entity")  # type: ignore


def normalize_href(href: str) -> str:
    """Encode query parameters in href to match expected STAC format."""
    parsed = urlparse(href)
    query = urlencode(parse_qsl(parsed.query), safe="")  # encode ":" -> "%3A"
    return urlunparse(parsed._replace(query=query))


class StacLinksTitleMiddleware(BaseHTTPMiddleware):
    """Middleware used to update links with title"""

    def __init__(self, app: FastAPI, title: str = "Default Title"):
        """
        Initialize the middleware.

        Args:
            app: The FastAPI application instance to attach the middleware to.
            title: Default title to use for STAC links if no specific title is provided.
        """
        super().__init__(app)
        self.title = title

    async def dispatch(self, request: Request, call_next):
        """
        Intercept and modify outgoing responses to ensure all STAC links have proper titles.

        This middleware method:
        1. Awaits the response from the next handler.
        2. Reads and parses the response body as JSON.
        3. Updates the "title" property of each link using `get_link_title`.
        4. Rebuilds the response without the original Content-Length header to prevent mismatches.
        5. If the response body is not JSON, returns it unchanged.

        Args:
            request: The incoming FastAPI Request object.
            call_next: The next ASGI handler in the middleware chain.

        Returns:
            A FastAPI Response object with updated STAC link titles.
        """
        response = await call_next(request)

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            data = json.loads(body)

            if isinstance(data, dict) and "links" in data:
                for link in data["links"]:
                    if isinstance(link, dict):
                        # normalize href to decode any %xx
                        if "href" in link:
                            link["href"] = normalize_href(link["href"])
                        # update title
                        link["title"] = get_link_title(link, data)

            headers = dict(response.headers)
            headers.pop("content-length", None)

            response = Response(
                content=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                status_code=response.status_code,
                headers=headers,
                media_type="application/json",
            )
        except Exception:  # pylint: disable = broad-exception-caught
            headers = dict(response.headers)
            headers.pop("content-length", None)

            response = Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
                media_type=response.headers.get("content-type"),
            )

        return response


def insert_middleware_at(app: FastAPI, index: int, middleware: Middleware):
    """Insert the given middleware at the specified index in a FastAPI application.

    Args:
        app (FastAPI): FastAPI application
        index (int): index at which the middleware has to be inserted
        middleware (Middleware): Middleware to insert

    Raises:
        RuntimeError: if the application has already started

    Returns:
        FastAPI: The modified FastAPI application instance with the required middleware.
    """
    if app.middleware_stack:
        raise RuntimeError("Cannot add middleware after an application has started")
    if not any(m.cls == middleware.cls for m in app.user_middleware):
        logger.debug("Adding %s", middleware)
        app.user_middleware.insert(index, middleware)
    return app


def insert_middleware_after(
    app: FastAPI,
    previous_mw_class: _MiddlewareFactory,
    middleware_class: _MiddlewareFactory[P],
    *args: P.args,
    **kwargs: P.kwargs,
):
    """Insert the given middleware after an existing one in a FastAPI application.

    Args:
        app (FastAPI): FastAPI application
        previous_mw_class (str): Class of middleware after which the new middleware has to be inserted
        middleware_class (Middleware): Class of middleware to insert
        args: args for middleware_class constructor
        kwargs: kwargs for middleware_class constructor

    Raises:
        RuntimeError: if the application has already started

    Returns:
        FastAPI: The modified FastAPI application instance with the required middleware.
    """
    existing_middlewares = [middleware.cls for middleware in app.user_middleware]
    middleware_index = existing_middlewares.index(previous_mw_class)
    return insert_middleware_at(app, middleware_index + 1, Middleware(middleware_class, *args, **kwargs))


def apply_middlewares(app: FastAPI):
    """
    Applies middlewares and authentication routes to the FastAPI application.

    Args:
        app (FastAPI): The FastAPI application instance.

    Returns:
        FastAPI: The modified FastAPI application instance with the required middlewares and authentication routes.
    """
    # Get the oauth2 router
    oauth2_router = oauth2.get_router(app)

    # Add it to the FastAPI application
    app.include_router(
        oauth2_router,
        tags=["Authentication"],
        prefix=oauth2.AUTH_PREFIX,
        include_in_schema=True,
    )
    return app
