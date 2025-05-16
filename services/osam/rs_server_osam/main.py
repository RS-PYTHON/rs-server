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

"""rs dpr service main module."""

import logging
import os

from contextlib import asynccontextmanager

# from dask.distributed import LocalCluster
from fastapi import APIRouter, FastAPI
from starlette.responses import JSONResponse
from starlette.status import (  # pylint: disable=C0411
    HTTP_200_OK,
)

from object_storage_access_manager import opentelemetry


# Initialize a FastAPI application
app = FastAPI(title="osam-service", root_path="", debug=True)
router = APIRouter(tags=["OSAM service"])

logger = logging.getLogger("my_logger")
logger.setLevel(logging.DEBUG)


def env_bool(var: str, default: bool) -> bool:
    """
    Return True if an environemnt variable is set to 1, true or yes (case insensitive).
    Return False if set to 0, false or no (case insensitive).
    Return the default value if not set or set to a different value.
    """
    val = os.getenv(var, str(default)).lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return True
    if val in ("n", "no", "f", "false", "off", "0"):
        return False
    return default



@asynccontextmanager
async def app_lifespan(fastapi_app: FastAPI):
    """Lifespann app to be implemented with start up / stop logic"""
    logger.info("Starting up the application...")
    fastapi_app.extra["local_mode"] = env_bool("RSPY_LOCAL_MODE", default=False)
    # Yield control back to the application (this is where the app will run)
    yield

    # Shutdown logic (cleanup)
    logger.info("Shutting down the application...")
    logger.info("Application gracefully stopped...")


# Health check route
@router.get("/_mgmt/ping", include_in_schema=False)
async def ping():
    """Liveliness probe."""
    return JSONResponse(status_code=HTTP_200_OK, content="Healthy")


app.include_router(router)
app.router.lifespan_context = app_lifespan  # type: ignore
opentelemetry.init_traces(app, "osam.service")
