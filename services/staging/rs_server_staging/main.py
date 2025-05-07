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
import copy

# pylint: disable=E0401
import os
import pathlib
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from string import Template
from time import sleep
from typing import Annotated

import httpx
import yaml
from dask.distributed import LocalCluster
from fastapi import APIRouter, Depends, FastAPI, Path, Security
from httpx._config import DEFAULT_TIMEOUT_CONFIG
from pygeoapi.api import API
from pygeoapi.process.base import JobNotFoundError
from pygeoapi.process.manager.postgresql import PostgreSQLManager
from pygeoapi.provider.postgresql import get_engine
from rs_server_common import settings as common_settings
from rs_server_common.authentication.apikey import APIKEY_AUTH_HEADER
from rs_server_common.authentication.authentication import auth_validation
from rs_server_common.middlewares import (
    AuthenticationMiddleware,
    HandleExceptionsMiddleware,
    apply_middlewares,
)
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils2 import filelock
from rs_server_staging import Base
from rs_server_staging.processors import processors
from rs_server_staging.staging_endpoints_validation import (
    validate_request,
    validate_response,
)
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import (
    HTTPException as StarletteHTTPException,  # pylint: disable=C0411
)
from starlette.middleware.cors import CORSMiddleware  # pylint: disable=C0411
from starlette.requests import Request  # pylint: disable=C0411
from starlette.responses import JSONResponse  # pylint: disable=C0411
from starlette.status import (  # pylint: disable=C0411
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

# DON'T REMOVE (needed for SQLAlchemy)
from . import jobs_table  # pylint: disable=unused-import

# flake8: noqa: F401
# pylint: disable=W0611
from .rspy_models import ProcessMetadataModel

REFRESH_TOKENS_TIMEOUT = 40

logger = Logging.default(__name__)

# Initialize a FastAPI application
app = FastAPI(title="rs-staging", root_path="", debug=True)
router = APIRouter(tags=["Staging service"])

JOB_ATTRS_MAPPING = {"identifier": "jobID"}
OGC_UNCOMPLIANT_JOB_ATTRS = ["_sa_instance_state", "location", "mimetype"]


def ogc_error_response(status_code: int, detail: str):
    """Generate an OGC-compliant error response"""
    error_response = {
        "type": f"https://developer.mozilla.org/en/docs/Web/HTTP/Reference/Status/{status_code}",
        "status": status_code,
        "detail": detail,
    }
    return JSONResponse(status_code=status_code, content=error_response)


class DatabaseJobFormatError(Exception):
    """Exception raised when an error occurred during the init of a provider."""


class JobsFormatError(Exception):
    """Exception raised when an error occurred during the init of a provider."""


def must_be_authenticated(path: str) -> bool:
    """Return true if a user must be authenticated to use this endpoint route path."""

    no_auth = (path in ["/api", "/api.html", "/health", "/_mgmt/ping"]) or path.startswith("/auth/")
    return not no_auth


if common_settings.CLUSTER_MODE:

    async def just_for_the_lock_icon(
        apikey_value: Annotated[str, Security(APIKEY_AUTH_HEADER)] = "",  # pylint: disable=unused-argument
    ):
        """Dummy function to add a lock icon in Swagger to enter an API key."""

else:

    async def just_for_the_lock_icon():  # type: ignore # different signature than above
        """In local mode it does nothing."""


async def validate_request_dependency(request: Request):
    """Dependency to validate the body of the input request"""
    await validate_request(request)


app.add_middleware(AuthenticationMiddleware, must_be_authenticated=must_be_authenticated)
app.add_middleware(HandleExceptionsMiddleware)

# In cluster mode, add the oauth2 authentication
if common_settings.CLUSTER_MODE:
    app = apply_middlewares(app)

# CORS enabled origins
app.add_middleware(CORSMiddleware)


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
    registers the ENUM type JobStatus and the 'job' tables if they don't already exist.

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
    # Create jobs table
    process_manager = init_db()
    # In local mode, if the gateway is not defined, create a dask LocalCluster
    cluster = None
    if common_settings.LOCAL_MODE and ("RSPY_DASK_STAGING_CLUSTER_NAME" not in os.environ):
        # Create the LocalCluster only in local mode
        cluster = LocalCluster()
        logger.info("Local Dask cluster created at startup.")

    fastapi_app.extra["process_manager"] = process_manager
    # fastapi_app.extra["db_table"] = db.table("jobs")
    fastapi_app.extra["dask_cluster"] = cluster
    # token refereshment logic
    fastapi_app.extra["station_token_list"] = []
    fastapi_app.extra["station_token_list_lock"] = threading.Lock()

    common_settings.set_http_client(httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_CONFIG))

    # Yield control back to the application (this is where the app will run)
    yield

    # Shutdown logic (cleanup)
    logger.info("Shutting down the application...")
    if common_settings.LOCAL_MODE and cluster:
        cluster.close()
        logger.info("Local Dask cluster shut down.")
    logger.info("Application gracefully stopped...")


# Health check route
@router.get("/_mgmt/ping", include_in_schema=False)
async def ping():
    """Liveliness probe."""
    return JSONResponse(status_code=HTTP_200_OK, content="Healthy")


@router.get("/processes", dependencies=[Depends(just_for_the_lock_icon), Depends(validate_request_dependency)])
async def get_processes(request: Request):
    """Returns list of all available processes from config."""
    try:
        processes = {
            "processes": [],
            "links": [
                {"href": str(request.url), "rel": "self", "type": "application/json", "title": "List of processes"},
            ],
        }
        for resource in api.config["resources"]:
            processes["processes"].append(
                {
                    "id": api.config["resources"][resource]["processor"]["name"],
                    "version": "1.0.0",
                },
            )
        validate_response(request, processes)
        return JSONResponse(status_code=HTTP_200_OK, content=processes)

    except Exception as e:  # pylint: disable=W0718
        return ogc_error_response(HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.get(
    "/processes/{resource}",
    dependencies=[Depends(just_for_the_lock_icon), Depends(validate_request_dependency)],
)
async def get_resource(request: Request, resource: str):
    """Should return info about a specific resource."""
    # rs_processes_{resource}_read role needed to access this endpoint.
    if resource_info := next(  # pylint: disable=W0612
        (
            api.config["resources"][defined_resource]
            for defined_resource in api.config["resources"]
            if defined_resource == resource
        ),
        None,
    ):
        try:
            auth_validation("read", resource, request=request, staging_process=True)
            process = {
                "id": api.config["resources"][resource]["processor"]["name"],
                "version": "1.0.0",
            }
            validate_response(request, process)
            return JSONResponse(status_code=HTTP_200_OK, content=process)

        except Exception as e:  # pylint: disable=W0718
            return ogc_error_response(HTTP_500_INTERNAL_SERVER_ERROR, str(e))
    return ogc_error_response(HTTP_404_NOT_FOUND, f"Resource {resource} not found")


def format_job_data(job: dict):
    """
    Method to apply reformatting on job data to make it compliant with OGC (process) standards
    Args:
        job: information on a specific job to fromat: the job must have the same attributes
        than the columns from the PostgreSql database
    Result:
        reformatted and validated job_data variable to put in the response
    """
    # Check that the input job have the same struture as the jobs contained in the PostgreSQL database
    if "identifier" not in job:
        raise DatabaseJobFormatError(
            """Input job must have the same structure than the jobs stored in the """
            """PostgreSql database: attribute 'identifier' is missing""",
        )
    job_data = copy.deepcopy(job)
    # Rename attribute "identifier" to be compliant with OGC standards
    job_data[JOB_ATTRS_MAPPING["identifier"]] = job_data.pop("identifier")
    # Remove attributes which should not be part of the response
    for attr in OGC_UNCOMPLIANT_JOB_ATTRS:
        if attr in job_data:
            job_data.pop(attr)
    for key, value in job_data.items():
        # Reformat datetime object to string
        if isinstance(value, datetime):
            job_data[key] = value.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Remove "finished" attribute if its value is None
    if "finished" in job_data and job_data.get("finished") is None:
        job_data.pop("finished")
    return job_data


def format_jobs_data(jobs: dict):
    """
    Method validate information on all existing jobs

    Args:
        jobs: information on all existing jobs
    Result:
        reformatted and validated jobs_data variable to provide to the response
    """
    if not isinstance(jobs, dict):
        raise JobsFormatError("Expected a dictionary as input")
    if "jobs" not in jobs:
        raise JobsFormatError("Invalid format for input jobs: missing 'jobs' key")
    jobs_data = copy.deepcopy(jobs)
    # Add "links" mandatory field to the response
    jobs_data.update(
        {
            "links": [
                {
                    "href": "string",
                    "rel": "service",
                    "type": "application/json",
                    "hreflang": "en",
                    "title": "List of jobs",
                },
            ],
        },
    )
    # Remove SQLAlchemy _sa_instance_state objects and convert datetime
    for i, job_data in enumerate(jobs_data["jobs"]):
        jobs_data["jobs"][i] = format_job_data(job_data)
    return jobs_data


# Endpoint to execute the staging process and generate a job ID
@router.post("/processes/{resource}/execution", dependencies=[Depends(just_for_the_lock_icon)])
async def execute_process(
    request: Request,
    resource: str,
    data: ProcessMetadataModel,
):  # pylint: disable=unused-argument
    """Used to execute processing jobs."""

    # check if the input resource exists
    if resource not in api.config["resources"]:
        return ogc_error_response(HTTP_404_NOT_FOUND, f"Process resource '{resource}' not found")

    # Validate request payload
    try:
        valid_body = await validate_request(request)
        # rs_processes_{resource}_execute role needed to access this endpoint.
        auth_validation("execute", resource, request=request, staging_process=True)
    except Exception as e:  # pylint: disable=W0718
        # Handle exceptions and return an appropriate error message
        return ogc_error_response(HTTP_500_INTERNAL_SERVER_ERROR, str(e))

    processor_name = api.config["resources"][resource]["processor"]["name"]
    if processor_name in processors:
        processor = processors[processor_name]
        _, staging_status = await processor(
            request,
            app.extra["process_manager"],
            app.extra["dask_cluster"],
            app.extra["station_token_list"],
            app.extra["station_token_list_lock"],
        ).execute(valid_body["inputs"])

        # Get identifier of the current job
        status_dict = {
            "accepted": HTTP_201_CREATED,
            "running": HTTP_201_CREATED,
            "successful": HTTP_201_CREATED,
            "failed": HTTP_500_INTERNAL_SERVER_ERROR,
            "dismissed": HTTP_500_INTERNAL_SERVER_ERROR,
        }
        id_key = [status for status in status_dict if status in staging_status][0]
        formatted_job_data = format_job_data(app.extra["process_manager"].get_job(staging_status[id_key]))
        validate_response(request, formatted_job_data, HTTP_201_CREATED)
        return JSONResponse(status_code=HTTP_201_CREATED, content=formatted_job_data)
    return ogc_error_response(HTTP_404_NOT_FOUND, f"Processor '{processor_name}' not found")


# Endpoint to get the status of a job by job_id
@router.get("/jobs/{job_id}", dependencies=[Depends(just_for_the_lock_icon), Depends(validate_request_dependency)])
async def get_job_status_endpoint(request: Request, job_id: str = Path(..., title="The ID of the job")):
    """Used to get status of processing job."""
    try:
        job = app.extra["process_manager"].get_job(job_id)
    except JobNotFoundError:  # pylint: disable=W0718
        # Handle case when job_id is not found
        return ogc_error_response(HTTP_404_NOT_FOUND, f"Job with ID {job_id} not found")

    try:
        auth_validation("read", job["processID"], request=request, staging_process=True)
        formatted_job_data = format_job_data(job)
        validate_response(request, formatted_job_data)
        return JSONResponse(status_code=HTTP_200_OK, content=formatted_job_data)
    except Exception as e:  # pylint: disable=W0718
        return ogc_error_response(HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.get("/jobs", dependencies=[Depends(just_for_the_lock_icon), Depends(validate_request_dependency)])
async def get_jobs_endpoint(request: Request):
    """Returns the status of all jobs."""
    try:
        # Generate an output conform to OGC process specifications
        formatted_jobs_data = format_jobs_data(app.extra["process_manager"].get_jobs())
        validate_response(request, formatted_jobs_data)
        return JSONResponse(status_code=HTTP_200_OK, content=formatted_jobs_data)
    except Exception as e:  # pylint: disable=W0718
        # Handle exceptions and return an appropriate error message
        return ogc_error_response(HTTP_404_NOT_FOUND, str(e))


@router.delete("/jobs/{job_id}", dependencies=[Depends(just_for_the_lock_icon), Depends(validate_request_dependency)])
async def delete_job_endpoint(request: Request, job_id: str = Path(..., title="The ID of the job to delete")):
    """Deletes a specific job from the database."""
    try:
        job = app.extra["process_manager"].get_job(job_id)
    # Handle case when job_id is not found
    except JobNotFoundError:  # pylint: disable=W0718
        return ogc_error_response(HTTP_404_NOT_FOUND, f"Job with ID {job_id} not found")
    try:
        auth_validation("dismiss", job["processID"], request=request, staging_process=True)
        app.extra["process_manager"].delete_job(job_id)
        # Create job response with a status message to confirm the job deletion
        job["message"] = f"Job {job_id} deleted successfully"
        formatted_job_data = format_job_data(job)
        validate_response(request, formatted_job_data)
        return JSONResponse(status_code=HTTP_200_OK, content=formatted_job_data)
    except Exception as e:  # pylint: disable=W0718
        return ogc_error_response(HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.get(
    "/jobs/{job_id}/results",
    dependencies=[Depends(just_for_the_lock_icon), Depends(validate_request_dependency)],
)
async def get_specific_job_result_endpoint(request: Request, job_id: str = Path(..., title="The ID of the job")):
    """Get result from a specific job."""
    try:
        # Query the database to find the job by job_id
        job = app.extra["process_manager"].get_job(job_id)
    except JobNotFoundError:
        return ogc_error_response(HTTP_404_NOT_FOUND, f"Job with ID {job_id} not found")
    try:
        auth_validation("read", job["processID"], request=request, staging_process=True)
        validate_response(request, job["status"])
        return JSONResponse(status_code=HTTP_200_OK, content=job["status"])
    except Exception as e:  # pylint: disable=W0718
        return ogc_error_response(HTTP_500_INTERNAL_SERVER_ERROR, str(e))


if common_settings.LOCAL_MODE:

    @router.post("/staging/dask/auth", include_in_schema=False)
    async def dask_auth(local_dask_username: str, local_dask_password: str):
        """Set dask cluster authentication, only in local mode."""
        os.environ["LOCAL_DASK_USERNAME"] = local_dask_username
        os.environ["LOCAL_DASK_PASSWORD"] = local_dask_password


# Configure OpenTelemetry
init_opentelemetry.init_traces(app, "rs.server.staging")

app.include_router(router)
app.router.lifespan_context = app_lifespan

# Mount pygeoapi endpoints
app.mount(path="/oapi", app=api)
