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

"""rs server staging main module."""
# pylint: disable=E0401
import os
import pathlib
from contextlib import asynccontextmanager
from string import Template
from time import sleep

import yaml
from dask.distributed import LocalCluster
from fastapi import APIRouter, FastAPI, HTTPException, Path
from pygeoapi.api import API
from pygeoapi.process.manager.postgresql import PostgreSQLManager
from pygeoapi.provider.postgresql import get_engine
from rs_server_common.authentication.authentication_to_external import (
    init_rs_server_config_yaml,
)
from rs_server_common.db import Base
from rs_server_common.settings import env_bool
from rs_server_common.utils import opentelemetry
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import filelock
from rs_server_staging.processors import processors
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from .rspy_models import ProcessMetadataModel

logger = Logging.default(__name__)

# Initialize a FastAPI application
app = FastAPI(title="rs-staging", root_path="", debug=True)
router = APIRouter(tags=["Staging service"])

# CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
):  # pylint: disable= unused-argument
    """HTTP handler"""
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})


os.environ["PYGEOAPI_OPENAPI"] = ""  # not used


def get_config_path() -> pathlib.Path:
    """Return the pygeoapi configuration path and set the PYGEOAPI_CONFIG env var accordingly."""
    path = pathlib.Path(__file__).parent.parent / "config" / "staging.yaml"
    os.environ["PYGEOAPI_CONFIG"] = str(path)
    return path


def get_config_contents() -> dict:
    """Return the pygeoapi configuration yaml file contents."""
    # Open the configuration file
    with open(get_config_path(), encoding="utf8") as opened:
        contents = opened.read()

        # Replace env vars by their value
        contents = Template(contents).substitute(os.environ)

        # Parse contents as yaml
        return yaml.safe_load(contents)


def init_pygeoapi() -> API:
    """Init pygeoapi"""
    return API(get_config_contents(), "")


api = init_pygeoapi()


def __filelock(func):
    """Avoid concurrent writing to the database using a file locK."""
    return filelock(func, "RSPY_WORKING_DIR")


@__filelock
def init_db(pause: int = 3, timeout: int | None = None) -> PostgreSQLManager:
    """Initialize the PostgreSQL database connection and sets up required table and ENUM type.

    This function constructs the database URL using environment variables for PostgreSQL
    credentials, host, port, and database name. It then creates an SQLAlchemy engine and
    registers the ENUM type EStagingStatus and the 'job' tables if they don't already exist.

    Environment Variables:
        - POSTGRES_USER: Username for database authentication.
        - POSTGRES_PASSWORD: Password for the database.
        - POSTGRES_HOST: Hostname of the PostgreSQL server.
        - POSTGRES_PORT: Port number of the PostgreSQL server.
        - POSTGRES_DB: Database name.

    Args:
        pause: pause in seconds to wait for the database connection.
        timeout: timeout in seconds to wait for the database connection.

    Returns:
        PostgreSQLManager instance
    """
    manager_def = api.config["manager"]
    if not manager_def or not isinstance(manager_def, dict) or not isinstance(manager_def["connection"], dict):
        message = "Error reading the manager definition for pygeoapi PostgreSQL Manager"
        logger.error(message)
        raise RuntimeError(message)
    connection = manager_def["connection"]

    # Create SQL Alchemy engine
    engine = get_engine(**connection)

    while True:
        try:
            # This registers the ENUM type and creates the jobs table if they do not exist
            Base.metadata.create_all(bind=engine)
            logger.info(f"Reached {engine.url!r}")
            logger.info("Database table and ENUM type created successfully.")
            break

        # It fails if the database is unreachable. Wait a few seconds and try again.
        except SQLAlchemyError:
            logger.warning(f"Trying to reach {engine.url!r}")

            # Sleep for n seconds and raise exception if timeout is reached.
            if timeout is not None:
                timeout -= pause
                if timeout < 0:
                    raise
            sleep(pause)

    # Initialize PostgreSQLManager with the manager configuration
    return PostgreSQLManager(manager_def)


# Create Dask LocalCluster when the application starts
@asynccontextmanager
async def app_lifespan(fastapi_app: FastAPI):  # pylint: disable=too-many-statements
    """Asynchronous context manager to handle the lifecycle of the FastAPI application,
    managing the creation and shutdown of a Dask cluster.

    This function is responsible for setting up a Dask cluster when the FastAPI application starts,
    either using a `LocalCluster` or connecting to an existing cluster via `Gateway`, depending
    on the application settings. The Dask cluster is closed during the application's shutdown phase.

    Args:
        fastapi_app (FastAPI): The FastAPI application instance.

    Yields:
        None: Control is yielded back to the application, allowing it to run while the Dask cluster is active.

    Startup Logic:
        - If `CLUSTER_MODE` is enabled in settings, the function attempts to connect to an existing
          Dask cluster via the `Gateway`. If no existing cluster is found, a new one is created.
        - If `CLUSTER_MODE` is disabled, a `LocalCluster` is created and scaled to 8 workers.
        - The Dask cluster information is stored in `app.extra["dask_cluster"]`.

    Shutdown Logic:
        - When the application shuts down, the Dask cluster is closed if it was a `LocalCluster`.

    Notes:
        - The Dask cluster is configured to scale based on the environment.
        - If connecting to a remote cluster using `Gateway`, ensure correct access rights.

    Raises:
        KeyError: If no clusters are found during an attempt to connect via the `Gateway`.
    """
    logger.info("Starting up the application...")
    # Init the rs-server configuration file for authentication to the external stations
    init_rs_server_config_yaml()
    # Create jobs table
    process_manager = init_db()

    cluster = None
    if env_bool("RSPY_LOCAL_MODE", default=False):
        # Create the LocalCluster only in local mode
        cluster = LocalCluster()
        logger.info("Local Dask cluster created at startup.")

    fastapi_app.extra["process_manager"] = process_manager
    # fastapi_app.extra["db_table"] = db.table("jobs")
    fastapi_app.extra["dask_cluster"] = cluster

    # Yield control back to the application (this is where the app will run)
    yield

    # Shutdown logic (cleanup)
    logger.info("Shutting down the application...")
    if env_bool("RSPY_LOCAL_MODE", default=False) and cluster:
        cluster.close()
        logger.info("Local Dask cluster shut down.")


# Health check route
@router.get("/_mgmt/ping", include_in_schema=False)
async def ping():
    """Liveliness probe."""
    return JSONResponse(status_code=HTTP_200_OK, content="Healthy")


@router.get("/processes")
async def get_processes():
    """Returns list of all available processes from config."""
    if processes := [
        {"name": resource, "processor": api.config["resources"][resource]["processor"]["name"]}
        for resource in api.config["resources"]
    ]:
        return JSONResponse(status_code=HTTP_200_OK, content={"processes": processes})
    return JSONResponse(status_code=HTTP_404_NOT_FOUND, content="No processes found")


@router.get("/processes/{resource}")
async def get_resource(resource: str):
    """Should return info about a specific resource."""
    if resource_info := next(
        (
            api.config["resources"][defined_resource]
            for defined_resource in api.config["resources"]
            if defined_resource == resource
        ),
        None,
    ):
        return JSONResponse(status_code=HTTP_200_OK, content=resource_info)
    return JSONResponse(status_code=HTTP_404_NOT_FOUND, content={"detail": "Resource not found"})


# Endpoint to execute the staging process and generate a job ID
@router.post("/processes/{resource}/execution")
async def execute_process(req: Request, resource: str, data: ProcessMetadataModel):
    """Used to execute processing jobs."""
    if resource not in api.config["resources"]:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Process resource '{resource}' not found")

    processor_name = api.config["resources"][resource]["processor"]["name"]
    if processor_name in processors:
        processor = processors[processor_name]
        status = await processor(
            req,
            data.inputs.items,
            data.inputs.collection.id,
            data.outputs["result"].id,
            data.inputs.provider,
            app.extra["process_manager"],
            app.extra["dask_cluster"],
        ).execute()
        return JSONResponse(status_code=HTTP_200_OK, content={"status": status})

    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Processor '{processor_name}' not found")


# Endpoint to get the status of a job by job_id
@router.get("/jobs/{job_id}")
async def get_job_status_endpoint(job_id: str = Path(..., title="The ID of the job")):
    """Used to get status of processing job."""
    job = app.extra["process_manager"].get_job(job_id)
    if job:
        return job
    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")


@router.get("/jobs")
async def get_jobs_endpoint():
    """Returns the status of all jobs."""
    try:
        return app.extra["process_manager"].get_jobs()
    except Exception as e:
        # Handle exceptions and return an appropriate error message
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e


@router.delete("/jobs/{job_id}")
async def delete_job_endpoint(job_id: str = Path(..., title="The ID of the job to delete")):
    """Deletes a specific job from the database."""
    success = app.extra["process_manager"].delete_job(job_id)
    if success:
        return {"message": f"Job {job_id} deleted successfully"}
    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")


@router.get("/jobs/{job_id}/results")
async def get_specific_job_result_endpoint(job_id: str = Path(..., title="The ID of the job")):
    """Get result from a specific job."""
    # Query the database to find the job by job_id
    job = app.extra["process_manager"].get_job(job_id)
    if job:
        return JSONResponse(status_code=HTTP_200_OK, content=job["status"])

    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")


# Configure OpenTelemetry
opentelemetry.init_traces(app, "rs.server.staging")

app.include_router(router)
app.router.lifespan_context = app_lifespan

# Mount pygeoapi endpoints
app.mount(path="/oapi", app=api)
