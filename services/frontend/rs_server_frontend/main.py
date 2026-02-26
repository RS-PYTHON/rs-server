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

"""The frontend application."""

import json
import os
from os import environ as env

from fastapi import FastAPI
from rs_server_common.middlewares import HandleExceptionsMiddleware, HealthMiddleware
from rs_server_frontend import __version__


class FrontendFailed(BaseException):
    """Exception raised if the frontend initialization failed."""


class Frontend:
    """The frontend application."""

    def __init__(self):
        """Create a frontend application.

        The frontend serves the rs-server REST API documentation.
        This documentation is an openapi specification loaded from a json file.
        This file location is given by the RSPY_OPENAPI_FILE environment variable.

        This file is loaded during the frontend application initialization
        and is kept in memory cache for the entire life of the application.

        A specific FrontendFailed exception is raised if the openapi loading failed.
        """

        # For cluster deployment: override the swagger /docs URL from an environment variable.
        # Also set the openapi.json URL under the same path.
        try:
            docs_url = env["RSPY_DOCS_URL"].strip("/")
            docs_params = {"docs_url": f"/{docs_url}", "openapi_url": f"/{docs_url}/openapi.json"}
        except KeyError:
            docs_params = {}

        try:
            self.openapi_spec: dict = self.load_openapi_spec()
            self.app: FastAPI = FastAPI(
                title="RS-Server",
                version=__version__,
                **docs_params,  # type: ignore
                # Same hardcoded values than in the apikey manager
                # (they don't appear in the openapi.json)
                swagger_ui_init_oauth={
                    "clientId": "(this value is not used)",
                    "appName": "API-Key Manager",
                    "usePkceWithAuthorizationCodeGrant": True,
                },
            )
            self.app.openapi = self.get_openapi  # type: ignore

            # Add middlewares. When sending a request, the middleware order must be:
            # Health -> HandleExceptions -> [any other middlewares ...]
            # Then after processing the request, the response is sent in the opposite order:
            # [any other middlewares ...] -> HandleExceptions -> Health

            # Catch all exceptions and return a JSONResponse
            self.app.add_middleware(HandleExceptionsMiddleware)
            HandleExceptionsMiddleware.disable_default_exception_handler(self.app)

            # More responsive /health and /ping endpoints
            self.app.add_middleware(HealthMiddleware)

        except BaseException as e:
            raise FrontendFailed("Unable to serve openapi specification.") from e

    @staticmethod
    def load_openapi_spec() -> dict:
        """Load the openapi specification.

        The openapi is loaded from a json file.
        This json file location is given by the environment variable RSPY_OPENAPI_FILE.

        An IOError is raised in case of errors during the file reading.
        A ValueError is raised in case of errors during the json parsing.

        Returns:
            the loaded openapi specification

        """
        openapi_location = os.getenv("RSPY_OPENAPI_FILE", "")
        try:
            with open(openapi_location, encoding="utf-8") as file:
                return json.load(file)
        except (FileNotFoundError, OSError) as e:
            raise type(e)(
                f"openapi spec was not found at {openapi_location!r}. "
                "Is the 'RSPY_OPENAPI_FILE' environment variable correctly set ?",
            ) from e
        except ValueError as e:
            raise ValueError(
                f"openapi spec was found at {openapi_location!r} but the file is not valid.",
            ) from e

    def get_openapi(self) -> dict:
        """Returns the openapi specification.

        Returns:
            the openapi specification as a dict.
        """
        return self.openapi_spec


def start_app() -> FastAPI:
    """Start the starlette app.

    Factory function that starts the application.

    Returns:
        the initialized application

    """
    return Frontend().app
