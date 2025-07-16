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

"""Custom STAC-style exception handlers for FastAPI applications."""

from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from stac_fastapi.api.errors import ErrorResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def register_stac_exception_handlers(app: FastAPI):
    """Attach STAC-style error handlers to the given FastAPI app."""

    def _build_stac_error_response(exc: HTTPException | StarletteHTTPException) -> JSONResponse:
        """Build STAC-style error response."""
        phrase = HTTPStatus(exc.status_code).phrase
        code = "".join(word.title() for word in phrase.split())

        # Return STAC-compliant error format
        payload: ErrorResponse = {
            "code": code,
            "description": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
        }
        return JSONResponse(status_code=exc.status_code, content=payload)

    @app.exception_handler(HTTPException)
    async def http_exc_handler(_request: Request, exc: HTTPException):
        """Override HTTPException to return a STAC-style ErrorResponse."""
        return _build_stac_error_response(exc)

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(_request: Request, exc: StarletteHTTPException):
        """Catch Starlette HTTPExceptions, including 404 from unknown routes."""
        return _build_stac_error_response(exc)
