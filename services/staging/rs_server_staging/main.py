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
from contextlib import asynccontextmanager

from dask.distributed import LocalCluster
from dask_gateway import Gateway
from dask_gateway import exceptions as dask_exceptions
from fastapi import APIRouter, FastAPI, HTTPException, Path
from pygeoapi.api import API
from pygeoapi.config import get_config
from rs_server_common import settings as common_settings
from rs_server_common.authentication.authentication_to_external import (
    init_rs_server_config_yaml,
)
from rs_server_common.utils.logging import Logging
from rs_server_staging.processors import processors
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_200_OK, HTTP_404_NOT_FOUND
from tinydb import Query, TinyDB

from .rspy_models import ProcessMetadataModel

logger = Logging.default(__name__)

# Initialize a FastAPI application
app = FastAPI(title="rs-staging", root_path="", debug=True)
router = APIRouter(tags=["Staging service"])
# Init the rs-server configuration file for authentication to extenal stations
init_rs_server_config_yaml()

# CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = API(get_config(os.environ["PYGEOAPI_CONFIG"]), os.environ["PYGEOAPI_OPENAPI"])


# Exception handlers
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
):  # pylint: disable= unused-argument
    """HTTP handler"""
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})


# Create Dask LocalCluster when the application starts
@asynccontextmanager
async def app_lifespan(fastapi_app: FastAPI):
    """
    Asynchronous context manager to handle the lifecycle of the FastAPI application,
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

    # Create the LocalCluster and Dask Client at startup
    if common_settings.CLUSTER_MODE:
        # to be implemented: write tcp
        try:
            gateway = Gateway(address=os.environ["DASK_GATEWAY__ADDRESS"], auth=os.environ["DASK_GATEWAY__AUTH__TYPE"])
            clusters = gateway.list_clusters()
            logger.debug(f"The list of clusters: {clusters}")
            cluster = gateway.connect(clusters[0].name)
        except KeyError as e:
            logger.error(f"Could not find the needed enveironment variable to use the daks gateway: {e}")
            raise RuntimeError from e
        except IndexError:
            logger.warning("There is no dask cluster to connect to. Creating a new one....")
            # TODO: Handle errors
            try:
                cluster = gateway.new_cluster()
            except dask_exceptions.GatewayServerError as e:
                logger.error(f"Failed to create a new Dask cluster: {e}")
                raise RuntimeError("Unable to create a Dask cluster") from e
            except dask_exceptions.AuthenticationError as e:
                logger.error(f"Authentication failed for Dask Gateway: {e}")
                raise RuntimeError("Authentication failed") from e
            except TimeoutError as e:
                logger.error(f"Timeout occurred while creating the Dask cluster: {e}")
                raise RuntimeError("Cluster creation timed out") from e
            except dask_exceptions.ClusterLimitExceeded as e:
                logger.error(f"Cluster limit exceeded: {e}")
                raise RuntimeError("Cannot create new cluster, limit reached") from e

            logger.debug("Creatied a new cluster ")
            logger.info("A new dask cluster has been created")

    else:
        cluster = LocalCluster()
        cluster.scale(8)
    logger.debug("Cluster dashboard: %s", cluster.dashboard_link)

    db_location = api.config["manager"]["connection"]
    if not os.path.isfile(db_location):
        with open(db_location, "w", encoding="utf-8"):
            pass
    db = TinyDB(db_location)
    fastapi_app.extra["db_table"] = db.table("jobs")
    fastapi_app.extra["dask_cluster"] = cluster
    logger.info("Local Dask cluster created at startup.")

    # Yield control back to the application (this is where the app will run)
    yield

    # Shutdown logic (cleanup)
    logger.info("Shutting down the application...")
    if not common_settings.CLUSTER_MODE and cluster:
        cluster.close()
        logger.info("Local Dask cluster shut down.")
    # Remove db when app-shutdown
    os.remove(db_location)


# Health check route
@router.get("/_mgmt/ping", include_in_schema=False)
async def ping():
    """Liveliness probe."""
    return JSONResponse(status_code=HTTP_200_OK, content="Healthy")


@router.get("/processes")
async def get_processes():
    """Returns list of all available processes from config."""
    processes = [
        {"name": resource, "processor": api.config["resources"][resource]["processor"]["name"]}
        for resource in api.config["resources"]
    ]
    return JSONResponse(status_code=200, content={"processes": processes})


@router.get("/processes/{resource}")
async def get_resource(resource: str):
    """Should return info about a specific resource."""
    for defined_resource in api.config["resources"]:
        if defined_resource == resource:
            return JSONResponse(status_code=HTTP_200_OK, content=api.config["resources"][defined_resource])


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
            app.extra["db_table"],
            app.extra["dask_cluster"],
        ).execute()
        return JSONResponse(status_code=HTTP_200_OK, content={"status": status})

    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Processor '{processor_name}' not found")


# Endpoint to get the status of a job by job_id
@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str = Path(..., title="The ID of the job")):
    """Used to get status of processing job."""
    job = app.extra["db_table"].get(Query().job_id == job_id)

    if job:
        return job

    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Job not found")


@router.get("/jobs")
async def get_jobs():
    """Returns the status of all jobs."""
    jobs = app.extra["db_table"].all()  # Retrieve all job entries from the jobs table

    if jobs:
        return JSONResponse(status_code=HTTP_200_OK, content=jobs)

    # If no jobs are found, return 404 with appropriate message
    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="No jobs found")


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str = Path(..., title="The ID of the job to delete")):
    """Deletes a specific job from the database."""
    job_query = Query()
    job = app.extra["db_table"].get(job_query.job_id == job_id)  # Check if the job exists

    if job:
        app.extra["db_table"].remove(job_query.job_id == job_id)  # Delete the job if found
        return JSONResponse(status_code=HTTP_200_OK, content={"message": f"Job {job_id} deleted successfully"})

    # Raise 404 if job not found
    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")


@router.get("/jobs/{job_id}/results")
async def get_specific_job_result(job_id):
    """Get result from a specific job."""
    return JSONResponse(status_code=HTTP_200_OK, content=job_id)


app.include_router(router)
app.router.lifespan_context = app_lifespan

# Mount pygeoapi endpoints
app.mount(path="/oapi", app=api)
