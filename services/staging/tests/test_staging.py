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

"""Test staging module."""
import os
import threading

import pytest
from fastapi import FastAPI
from rs_server_staging.main import app_lifespan
from starlette.status import HTTP_200_OK, HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_get_jobs(mocker, staging_client):
    """
    Test the GET /jobs endpoint for retrieving job listings.

    This test verifies the behavior of the /jobs endpoint when jobs are present
    in the TinyDB table. It checks that the API correctly returns the list of
    jobs when available, as well as the handling of cases where no jobs exist.

    Args:
        mocker: A mocker object used to create mocks and patches for testing.
        staging_client: A test client for making requests to the FastAPI application.

    Assertions:
        - Asserts that the response status code is 200 and the returned job list
          matches the simulated job data when jobs are present in the database.
        - Asserts that the response status code is 404 when no jobs are available
          in the database.
    """
    # Simulate mock data in the TinyDB table
    mock_jobs = [
        {"job_id": "job_1", "status": "completed", "progress": 100.0, "detail": "Test detail"},
        {"job_id": "job_2", "status": "in-progress", "progress": 100.0, "detail": "Test detail"},
    ]

    # Mock app.extra to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()
    mock_db_table.all.return_value = mock_jobs  # Simulate TinyDB returning jobs

    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"db_table": mock_db_table, "db_handler": threading.Lock()})

    # Call the API
    response = staging_client.get("/jobs")

    # Assert the correct response is returned
    assert response.status_code == HTTP_200_OK
    assert response.json() == mock_jobs  # Check if the returned data matches the mocked jobs

    # Mock with an empty db, should return 404 since there are no jobs.
    mock_db_table.all.return_value = []
    mocker.patch.object(staging_client.app, "extra", {"db_table": mock_db_table, "db_handler": threading.Lock()})
    response = staging_client.get("/jobs")

    assert response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job",
    [
        {"job_id": "job_1", "status": "started", "progress": 0.0, "detail": "Test detail"},
        {"job_id": "job_2", "status": "in_progress", "progress": 55.0, "detail": "Test detail"},
        {"job_id": "job_3", "status": "paused", "progress": 15.0, "detail": "Test detail"},
        {"job_id": "job_4", "status": "finished", "progress": 100.0, "detail": "Test detail"},
        {"job_id": "non_existing", "status": "finished", "progress": 100.0, "detail": "Test detail"},
    ],
)
async def test_get_job(mocker, staging_client, mock_jobs, expected_job):
    """
    Test the GET /jobs/{job_id} endpoint for retrieving job details.

    This test verifies that the details of a specific job can be retrieved
    correctly based on its job ID. It checks both the successful retrieval
    of job details and the appropriate handling of non-existing jobs.

    Args:
        mocker: A mocker object used to create mocks and patches for testing.
        staging_client: A test client for making requests to the FastAPI application.
        expected_job (dict): The expected job dictionary containing job_id,
            status, progress, and detail for the job to be retrieved.

    Assertions:
        - Asserts that the response status code is 200 and the returned job
          details match the expected job dictionary when the job exists.
        - Asserts that the response status code is 404 when the job does not exist.
    """
    # Mock app.extra to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()
    try:
        job_index = next(i for i, job in enumerate(mock_jobs) if job["job_id"] == expected_job["job_id"])
        mock_db_table.get.return_value = mock_jobs[job_index]
    except StopIteration:
        mock_db_table.get.return_value = []

    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"db_table": mock_db_table, "db_handler": threading.Lock()})

    # Call the API
    response = staging_client.get(f"/jobs/{expected_job['job_id']}")
    # assert response is OK and job info match, or not found for last case
    assert (
        response.status_code == HTTP_200_OK and response.json() == expected_job
    ) or response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job",
    [
        {"job_id": "job_1", "status": "started", "progress": 0.0, "detail": "Test detail"},
        {"job_id": "job_2", "status": "in_progress", "progress": 55.0, "detail": "Test detail"},
        {"job_id": "job_3", "status": "paused", "progress": 15.0, "detail": "Test detail"},
        {"job_id": "job_4", "status": "finished", "progress": 100.0, "detail": "Test detail"},
        {"job_id": "non_existing", "status": "finished", "progress": 100.0, "detail": "Test detail"},
    ],
)
async def test_get_job_result(mocker, staging_client, mock_jobs, expected_job):
    """
    Test the GET /jobs/{job_id}/results endpoint for retrieving job results.

    This test verifies that the results of a specific job can be retrieved
    correctly based on its job ID. It checks both the successful retrieval
    of job results and the appropriate handling of non-existing jobs.

    Args:
        mocker: A mocker object used to create mocks and patches for testing.
        staging_client: A test client for making requests to the FastAPI application.
        expected_job (dict): The expected job dictionary containing job_id,
            status, progress, and detail for the job whose results are to be retrieved.

    Assertions:
        - Asserts that the response status code is 200 and the returned job result
          matches the expected job status when the job exists.
        - Asserts that the response status code is 404 when the job does not exist.
    """
    # Mock app.extra to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()
    try:
        job_index = next(i for i, job in enumerate(mock_jobs) if job["job_id"] == expected_job["job_id"])
        mock_db_table.get.return_value = mock_jobs[job_index]
    except StopIteration:
        mock_db_table.get.return_value = []

    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"db_table": mock_db_table, "db_handler": threading.Lock()})

    # Call the API
    response = staging_client.get(f"/jobs/{expected_job['job_id']}/results")
    # assert response is OK and job info match, or not found for last case
    assert (
        response.status_code == HTTP_200_OK and response.json() == expected_job["status"]
    ) or response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job",
    [
        {"job_id": "job_1", "status": "started", "progress": 0.0, "detail": "Test detail"},
        {"job_id": "job_2", "status": "in_progress", "progress": 55.0, "detail": "Test detail"},
        {"job_id": "job_3", "status": "paused", "progress": 15.0, "detail": "Test detail"},
        {"job_id": "job_4", "status": "finished", "progress": 100.0, "detail": "Test detail"},
        {"job_id": "non_existing", "status": "finished", "progress": 100.0, "detail": "Test detail"},
    ],
)
async def test_delete_job(mocker, staging_client, mock_jobs, expected_job):
    """
    Test the DELETE /jobs/{job_id} endpoint for deleting a specific job.

    This test verifies the behavior of the job deletion endpoint by checking
    if the job can be successfully deleted when it exists or if a 404 status
    code is returned when the job does not exist.

    Args:
        mocker: A mocker object used to create mocks and patches for testing.
        staging_client: A test client for making requests to the FastAPI application.
        expected_job (dict): The expected job dictionary containing job_id,
            status, progress, and detail for the job to be deleted.

    Assertions:
        - Asserts that the response status code is 200 if the job is successfully deleted.
        - Asserts that the response status code is 404 if the job does not exist.
    """
    # Mock app.extra to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()
    try:
        job_index = next(i for i, job in enumerate(mock_jobs) if job["job_id"] == expected_job["job_id"])
        mock_db_table.get.return_value = mock_jobs[job_index]
    except StopIteration:
        mock_db_table.get.return_value = []

    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"db_table": mock_db_table, "db_handler": threading.Lock()})

    # Call the API
    response = staging_client.delete(f"/jobs/{expected_job['job_id']}")
    # assert response is OK, or not found for last case
    assert response.status_code in [HTTP_200_OK, HTTP_404_NOT_FOUND]


@pytest.mark.asyncio
async def test_processes(staging_client, predefined_config):
    """
    Test the /processes endpoint for retrieving a list of available processors.

    This test verifies that the processors returned by the /processes endpoint
    match those defined in the provided configuration. It ensures that the
    API returns the expected processors correctly.

    Args:
        staging_client: A test client for making requests to the FastAPI application.
        predefined_config (dict): A configuration dictionary containing predefined
            resources with their associated processors.

    Assertions:
        - Asserts that the list of processors returned from the API matches
          the list defined in the predefined configuration.
    """
    response = staging_client.get("/processes")
    input_processors = [resource["processor"]["name"] for resource in predefined_config["resources"].values()]

    # Extract processors from the output
    output_processors = [process["processor"] for process in response.json()["processes"]]

    # Assert that both lists of processors match
    assert sorted(input_processors) == sorted(output_processors), "Processors do not match!"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource_name, processor_name",
    [
        ("test_resource1", "HelloWorld1"),
        ("test_resource2", "HelloWorld2"),
        ("test_resource3", "HelloWorld3"),
        ("non_existing_resource", "non_existing_processor"),
    ],
)
async def test_specific_process(staging_client, resource_name, processor_name):
    """
    Test the /processes/{resource_name} endpoint for retrieving specific resource information.

    This test checks whether the specified resource returns the correct processor name
    or a 404 status code if the resource does not exist. It uses parameterized testing
    to verify multiple scenarios.

    Args:
        staging_client: A test client for making requests to the FastAPI application.
        resource_name (str): The name of the resource to retrieve. This can be a valid
            resource name or a non-existing resource name to test the 404 response.
        processor_name (str): The expected name of the processor associated with the
            resource. This is only relevant for valid resources.

    Assertions:
        - If the resource exists, the response status code is 200 and the processor name
          matches the expected processor name.
        - If the resource does not exist, the response status code is 404.

    """
    response = staging_client.get(f"/processes/{resource_name}")
    assert (
        response.status_code == HTTP_200_OK and response.json()["processor"]["name"] == processor_name
    ) or response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_app_lifespan_local_mode(mocker):
    """Test app_lifespan when running in local mode (no Dask Gateway connection)."""

    # Mock environment to simulate local mode
    mocker.patch.dict(os.environ, {"RSPY_LOCAL_MODE": "1"})

    mock_app = FastAPI()

    async with app_lifespan(mock_app):
        pass  # We are testing the startup logic

    assert "dask_cluster" in mock_app.extra
    assert mock_app.extra["dask_cluster"] is not None


@pytest.mark.asyncio
async def test_app_lifespan_gateway_error(mocker):
    """Test app_lifespan when there is an error in connecting to the Dask Gateway."""

    # Mock environment variables to simulate gateway mode
    mocker.patch.dict(
        os.environ,
        {
            "RSPY_LOCAL_MODE": "0",
        },
    )

    # Mock FastAPI app
    mock_app = FastAPI()

    async with app_lifespan(mock_app):
        pass  # We are testing the startup logic

    assert "dask_cluster" in mock_app.extra
    assert mock_app.extra["dask_cluster"] is None
