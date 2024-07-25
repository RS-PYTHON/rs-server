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
import uuid

from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel
from pygeoapi.api import API
from pygeoapi.config import get_config
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from tinydb import Query, TinyDB

from .processors import processors

db = TinyDB("db.json")
jobs_table = db.table("jobs")


# Use if you want to impose shaped-design of request
class ExecuteRequest(BaseModel):  # pylint: disable = too-few-public-methods
    """Class used to describe request structure."""

    job_id: str
    parameters: dict
    # Add any other fields you expect in the request body


# Initialize a FastAPI application
app = FastAPI(title="rs-staging", root_path="", debug=True)

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


# Exception handlers
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
):  # pylint: disable= unused-argument
    """HTTP handler"""
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})


# Health check route
@app.get("/_mgmt/ping")
async def ping():
    """Liveliness probe."""
    return {"status": "healthy"}


# Endpoint to execute the staging process and generate a job ID
@app.post("/processes/staging/execution")
async def execute_staging_process(request: dict):
    """Used to execute processing jobs."""
    job_id = str(uuid.uuid4())  # Generate a unique job ID
    parameters = request.get("parameters", {})
    processor_name = "HelloWorld"
    if processor_name in processors:
        processor = processors[processor_name]
        result = processor(parameters)

        # Store job status in TinyDB
        jobs_table.insert({"job_id": job_id, "status": "completedOK"})

        # Process result as needed and return a response
        return {"job_id": job_id, "message": "Process executed successfully", "result": result}

    raise HTTPException(status_code=404, detail=f"Processor '{processor_name}' not found")


# Endpoint to get the status of a job by job_id
@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str = Path(..., title="The ID of the job")):
    """Used to get status of processing job."""
    job = jobs_table.get(Query().job_id == job_id)

    if job:
        return job

    raise HTTPException(status_code=404, detail="Job not found")


# Mount pygeoapi endpoints
app.mount(path="/oapi", app=api)
