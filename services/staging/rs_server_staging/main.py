import pathlib

from fastapi import FastAPI, HTTPException, Path
from starlette.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from pydantic import BaseModel
from pygeoapi.api import API
from pygeoapi.config import get_config
import os
from pydantic import BaseModel
import uuid
from .processors import processors
from typing import Dict
from tinydb import TinyDB, Query

db = TinyDB('db.json')
jobs_table = db.table('jobs')

# Use if you want to impose shaped-design of request
class ExecuteRequest(BaseModel):
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
config_path = pathlib.Path("rs_server_staging/config/config.yml").absolute()
openapi_path = pathlib.Path("rs_server_staging/config/openapi.json").absolute()
os.environ['PYGEOAPI_CONFIG']  = str(config_path)
os.environ['PYGEOAPI_OPENAPI'] = str(openapi_path)
config = get_config(config_path)
openapi = openapi_path  # You should load the actual content of your OpenAPI spec here if it's not a file path

api = API(config, openapi)

# Exception handlers
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"message": exc.detail})

# Health check route
@app.get("/_mgmt/ping")
async def ping():
    return {"status": "healthy"}

# Endpoint to execute the staging process and generate a job ID
@app.post("/processes/staging/execution")
async def execute_staging_process(request: dict):
    job_id = str(uuid.uuid4())  # Generate a unique job ID
    parameters = request.get("parameters", {})
    processor_name = "HelloWorld"
    if processor_name in processors:
        processor = processors[processor_name]
        result = processor(parameters)

        # Store job status in TinyDB
        jobs_table.insert({'job_id': job_id, 'status': 'completedOK'})

        # Process result as needed and return a response
        return {"job_id": job_id, "message": "Process executed successfully", "result": result}

    raise HTTPException(status_code=404, detail=f"Processor '{processor_name}' not found")

# Endpoint to get the status of a job by job_id
@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str = Path(..., title="The ID of the job")):
    Job = Query()
    job = jobs_table.get(Job.job_id == job_id)

    if job:
        return job
    else:
        raise HTTPException(status_code=404, detail="Job not found")

# Mount pygeoapi endpoints
app.mount(path="/oapi", app=api)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
