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

"""Common functions for fastapi middlewares"""
import json
import os
import traceback
from collections.abc import Callable
from typing import Any, ParamSpec, TypedDict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import brotli
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from rs_server_common import settings as common_settings
from rs_server_common.authentication import authentication, oauth2
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.authentication.oauth2 import AUTH_PREFIX, LoginAndRedirect
from rs_server_common.utils.logging import Logging
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware, _MiddlewareFactory
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

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


class ErrorResponse(TypedDict):
    """A JSON error response returned by the API.

    The STAC API spec expects that `code` and `description` are both present in
    the payload.

    Attributes:
        code: A code representing the error, semantics are up to implementor.
        description: A description of the error.
    """

    code: str
    description: str


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


class HandleExceptionsMiddleware(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """
    Middleware to catch all exceptions and return a JSONResponse instead of raising them.
    This is useful in FastAPI when HttpExceptions are raised within the code but need to be handled gracefully.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        try:
            return await call_next(request)
        except StarletteHTTPException as http_exception:
            # Log stack trace and return HTTP exception details
            logger.error(traceback.format_exc())
            return JSONResponse(status_code=http_exception.status_code, content=str(http_exception.detail))
        except Exception as exception:  # pylint: disable=broad-exception-caught
            # Log stack trace and return generic error response
            logger.error(traceback.format_exc())
            return (
                JSONResponse(
                    content=ErrorResponse(code=exception.__class__.__name__, description=str(exception)),
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
                if self.is_bad_request(request, exception)
                else JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=str(exception))
            )

    def is_bad_request(self, request: Request, e: Exception) -> bool:
        """Determines if the request that raised this exception shall be considered as a bad request"""
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
    # Existing middlewares
    middleware_names = [middleware.cls for middleware in app.user_middleware]
    middleware_index = middleware_names.index(previous_mw_class)
    return insert_middleware_at(app, middleware_index + 1, Middleware(middleware_class, *args, **kwargs))


def apply_middlewares(app: FastAPI):
    """
    Applies necessary middlewares and authentication routes to the FastAPI application.

    This function ensures that:
    1. `SessionMiddleware` is inserted after `HandleExceptionsMiddleware` to enable cookie storage.
    2. OAuth2 authentication routes are added to the FastAPI application.

    Args:
        app (FastAPI): The FastAPI application instance.

    Raises:
        RuntimeError: If the function is called after the application has already started.

    Returns:
        FastAPI: The modified FastAPI application instance with the required middleware and authentication routes.
    """

    # Insert the SessionMiddleware (to save cookies) after the HandleExceptionsMiddleware middleware.
    # Code copy/pasted from app.add_middleware(SessionMiddleware, secret_key=cookie_secret)
    cookie_secret = os.environ["RSPY_COOKIE_SECRET"]
    insert_middleware_after(app, HandleExceptionsMiddleware, SessionMiddleware, secret_key=cookie_secret)

    # Get the oauth2 router
    oauth2_router = oauth2.get_router(app)

    # Add it to the FastAPI application
    app.include_router(
        oauth2_router,
        tags=["Authentication"],
        prefix=AUTH_PREFIX,
        include_in_schema=True,
    )
    return app
