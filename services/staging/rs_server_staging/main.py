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

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Path
from pygeoapi.api import API
from pygeoapi.config import get_config
from rs_server_staging.processors import processors
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_200_OK, HTTP_404_NOT_FOUND
from tinydb import Query, TinyDB

from .rspy_models import ProcessMetadataModel, RSPYFeatureCollectionModel

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

# Initialize pygeoapi API
# config_path = pathlib.Path("rs_server_staging/config/config.yml").absolute()
# openapi_path = pathlib.Path("rs_server_staging/config/openapi.json").absolute()
# os.environ['PYGEOAPI_CONFIG']  = str(config_path)
# os.environ['PYGEOAPI_OPENAPI'] = str(openapi_path)
# config = get_config(config_path)
# openapi = openapi_path  # You should load the actual content of your OpenAPI spec here if it's not a file path

api = API(get_config(os.environ["PYGEOAPI_CONFIG"]), os.environ["PYGEOAPI_OPENAPI"])
db = TinyDB(api.config["manager"]["connection"])
jobs_table = db.table("jobs")


# Exception handlers
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
):  # pylint: disable= unused-argument
    """HTTP handler"""
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})


# Health check route
@router.get("/_mgmt/ping", include_in_schema=False)
async def ping():
    """Liveliness probe."""
    return JSONResponse(status_code=HTTP_200_OK, content="Healthy")


@router.get("/processes")
async def get_processes():
    """Returns list of all available processes from config."""
    processes = [
        {"name": resource, "processor": api["config"]["resources"][resource]["processor"]["name"]}
        for resource in api["config"]["resources"]
    ]
    return JSONResponse(status_code=200, content={"processes": processes})


@router.get("/processes/{resource}")
async def get_resource():
    """Should return info about a specific resource."""
    return JSONResponse(status_code=HTTP_200_OK, content="Check")


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
            jobs_table,
        ).execute()
        return JSONResponse(status_code=HTTP_200_OK, content={"status": status})

    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Processor '{processor_name}' not found")


# Endpoint to get the status of a job by job_id
@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str = Path(..., title="The ID of the job")):
    """Used to get status of processing job."""
    job = jobs_table.get(Query().job_id == job_id)

    if job:
        return job

    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Job not found")


@router.get("/jobs")
async def get_jobs():
    """Returns the status of all jobs."""
    jobs = jobs_table.all()  # Retrieve all job entries from the jobs table

    if jobs:
        return JSONResponse(status_code=HTTP_200_OK, content=jobs)

    # If no jobs are found, return 404 with appropriate message
    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="No jobs found")


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str = Path(..., title="The ID of the job to delete")):
    """Deletes a specific job from the database."""
    JobQuery = Query()
    job = jobs_table.get(JobQuery.job_id == job_id)  # Check if the job exists

    if job:
        jobs_table.remove(JobQuery.job_id == job_id)  # Delete the job if found
        return JSONResponse(status_code=HTTP_200_OK, content={"message": f"Job {job_id} deleted successfully"})

    # Raise 404 if job not found
    raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=f"Job with ID {job_id} not found")


@router.get("/jobs/{job_id}/results")
async def get_specific_job_result(job_id):
    """Get result from a specific job."""
    return JSONResponse(status_code=HTTP_200_OK, content=job_id)


app.include_router(router)

# Mount pygeoapi endpoints
app.mount(path="/oapi", app=api)
