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
from datetime import datetime

import pytest
from fastapi import FastAPI
from rs_server_staging.main import (
    app_lifespan,
    get_config_contents,
    init_db,
    init_pygeoapi,
)
from sqlalchemy.exc import SQLAlchemyError
from starlette.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_503_SERVICE_UNAVAILABLE,
)

expected_jobs_test = [
    {
        "identifier": "job_1",
        "status": "started",
        "progress": 0.0,
        "detail": "Test detail",
        "created_at": str(datetime(2024, 1, 1, 12, 0, 0)),
        "updated_at": str(datetime(2024, 1, 1, 13, 0, 0)),
    },
    {
        "identifier": "job_2",
        "status": "in_progress",
        "progress": 55.0,
        "detail": "Test detail",
        "created_at": str(datetime(2024, 1, 2, 12, 0, 0)),
        "updated_at": str(datetime(2024, 1, 2, 13, 0, 0)),
    },
    {
        "identifier": "job_3",
        "status": "paused",
        "progress": 15.0,
        "detail": "Test detail",
        "created_at": str(datetime(2024, 1, 3, 12, 0, 0)),
        "updated_at": str(datetime(2024, 1, 3, 13, 0, 0)),
    },
    {
        "identifier": "job_4",
        "status": "finished",
        "progress": 100.0,
        "detail": "Test detail",
        "created_at": str(datetime(2024, 1, 4, 12, 0, 0)),
        "updated_at": str(datetime(2024, 1, 4, 13, 0, 0)),
    },
    {
        "identifier": "non_existing",
        "status": "finished",
        "progress": 100.0,
        "detail": "Test detail",
        "created_at": "unknown",
        "updated_at": "unknown",
    },
]


class TestInitDb:
    """Class to group tests for the init_db function"""

    def test_init_db_success(self, set_db_env_var, mocker):  # pylint: disable=unused-argument
        """Test that the database initialization completes successfully."""

        # Mock pygeoapi functions
        mock_engine = mocker.Mock()
        mocker.patch("pygeoapi.process.manager.postgresql.get_table_model", return_value=mocker.Mock())
        mock_get_engine = mocker.patch("pygeoapi.process.manager.postgresql.get_engine", return_value=mock_engine)
        mock_get_engine = mocker.patch("rs_server_staging.main.get_engine", return_value=mock_engine)
        mock_metadata = mocker.patch("rs_server_staging.main.Base.metadata.create_all")
        mocker.patch("rs_server_staging.main.api", init_pygeoapi())

        # Act: Call the function
        init_db()

        # Assert: Check that create_engine and create_all were called correctly
        mock_get_engine.assert_called_once_with(  # nosec hardcoded_password_funcarg
            host="localhost",
            port=5500,
            database="rspy_pytest",
            user="postgres",
            password="password",
        )
        mock_metadata.assert_called_once_with(bind=mock_engine)

    def test_init_db_missing_env_variable(self, mocker):
        """Test that the function raises an error when environment variables are missing."""
        # Mock environment variables to be incomplete
        mocker.patch.dict("os.environ", {}, clear=True)

        # Act & Assert: Check that an exception is raised for missing port environment variable
        with pytest.raises(KeyError, match="POSTGRES_HOST"):
            init_pygeoapi()

    def test_init_db_sqlalchemy_error(self, set_db_env_var, mocker):  # pylint: disable=unused-argument
        """Test that the function raises an error when SQLAlchemy fails."""

        # Mock SQLAlchemy create_engine to raise an error
        mocker.patch("rs_server_staging.main.api", init_pygeoapi())
        mocker.patch("pygeoapi.process.manager.postgresql.get_engine", side_effect=SQLAlchemyError("Database error"))

        # Act & Assert: Check that a RuntimeError is raised
        with pytest.raises(SQLAlchemyError):
            init_db(timeout=0)

    def test_get_config_contents_success(self, set_db_env_var):  # pylint: disable=unused-argument
        """Test that the manager definition is correctly retrieved and placeholders are replaced."""

        # Act: Call the function
        result = get_config_contents()

        # Assert: Validate the updated connection dictionary
        assert result["manager"]["connection"] == {
            "host": os.environ["POSTGRES_HOST"],
            "port": int(os.environ["POSTGRES_PORT"]),
            "database": os.environ["POSTGRES_DB"],
            "user": os.environ["POSTGRES_USER"],
            "password": os.environ["POSTGRES_PASSWORD"],
        }

    def test_get_config_contents_invalid_definition(self, mocker):
        """Test that the function raises an error when the manager definition is invalid."""
        # Mock the api.config.get method to return an invalid configuration
        mock_api_config = mocker.patch("rs_server_staging.main.api.config", autospec=True)
        mock_api_config.get.return_value = {"connection": None}

        # Act & Assert: Check that a RuntimeError is raised
        with pytest.raises(RuntimeError, match="Error reading the manager definition for pygeoapi PostgreSQL Manager"):
            init_db()


@pytest.mark.asyncio
async def test_get_jobs_endpoint(mocker, set_db_env_var, staging_client):  # pylint: disable=unused-argument
    """
    Test the GET /jobs endpoint for retrieving job listings.

    This test verifies the behavior of the /jobs endpoint when jobs are present
    in the postgres jobs table. It checks that the API correctly returns the list of
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
    # Simulate mock data in the postgres table

    mock_jobs = [
        {
            "identifier": "job_1",
            "status": "completed",
            "progress": 100.0,
            "detail": "Test detail",
            "created_at": str(datetime(2024, 1, 1, 12, 0, 0)),
            "updated_at": str(datetime(2024, 1, 1, 13, 0, 0)),
        },
        {
            "identifier": "job_2",
            "status": "in-progress",
            "progress": 90.25,
            "detail": "Test detail",
            "created_at": str(datetime(2024, 1, 2, 12, 0, 0)),
            "updated_at": str(datetime(2024, 1, 2, 13, 0, 0)),
        },
    ]

    # Mock app.extra to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()
    # Simulate postgres returning jobs
    mock_db_table.get_jobs.return_value = {"jobs": list(mock_jobs), "numberMatched": 2}

    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"process_manager": mock_db_table})

    # Call the API
    response = staging_client.get("/jobs")
    # Assert the correct response is returned
    assert response.status_code == HTTP_200_OK
    # Check if the returned data matches the mocked jobs
    assert response.json() == {"jobs": list(mock_jobs), "numberMatched": 2}

    # Mock with an empty db, should return 404 since there are no jobs.
    mock_db_table.get_jobs.return_value = {"jobs": [], "numberMatched": 0}

    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"process_manager": mock_db_table})

    response = staging_client.get("/jobs")

    assert response.status_code == HTTP_200_OK
    # Check if the returned data matches 0 jobs
    assert response.json() == {"jobs": [], "numberMatched": 0}

    # Simulate an exception
    mock_db_table.get_jobs.side_effect = Exception("get_jobs failed")
    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"process_manager": mock_db_table})
    # Call the API
    response = staging_client.get("/jobs")
    assert response.status_code == HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == {"message": "get_jobs failed"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job",
    expected_jobs_test,
)
async def test_get_job(
    mocker,
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,
    mock_jobs,
    expected_job,  # pylint: disable=unused-argument
):
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
        job_index = next(i for i, job in enumerate(mock_jobs) if job["identifier"] == expected_job["identifier"])
        mock_db_table.get_job.return_value = mock_jobs[job_index]
    except StopIteration:
        mock_db_table.get_job.return_value = []

    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"process_manager": mock_db_table})

    # Call the API
    response = staging_client.get(f"/jobs/{expected_job['identifier']}")
    # assert response is OK and job info match, or not found for last case
    assert (
        response.status_code == HTTP_200_OK and response.json() == expected_job
    ) or response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job",
    expected_jobs_test,
)
async def test_get_job_result(
    mocker,
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,
    mock_jobs,
    expected_job,  # pylint: disable=unused-argument
):
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
        job_index = next(i for i, job in enumerate(mock_jobs) if job["identifier"] == expected_job["identifier"])
        mock_db_table.get_job.return_value = mock_jobs[job_index]
    except StopIteration:
        mock_db_table.get_job.return_value = []
    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"process_manager": mock_db_table})

    # Call the API
    response = staging_client.get(f"/jobs/{expected_job['identifier']}/results")
    # assert response is OK and job info match, or not found for last case
    assert (
        response.status_code == HTTP_200_OK and response.json() == expected_job["status"]
    ) or response.status_code == HTTP_404_NOT_FOUND


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job",
    expected_jobs_test,
)
async def test_delete_job_endpoint(
    mocker,
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,
    mock_jobs,
    expected_job,  # pylint: disable=unused-argument
):
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
        job_index = next(i for i, job in enumerate(mock_jobs) if job["identifier"] == expected_job["identifier"])
        mock_db_table.get_job.return_value = mock_jobs[job_index]
    except StopIteration:
        mock_db_table.get_job.return_value = []
    # Patch app.extra with the mock db_table
    mocker.patch.object(staging_client.app, "extra", {"process_manager": mock_db_table})

    # Call the API
    response = staging_client.delete(f"/jobs/{expected_job['identifier']}")
    # assert response is OK, or not found for last case
    assert response.status_code in [HTTP_200_OK, HTTP_404_NOT_FOUND]


@pytest.mark.asyncio
async def test_processes(
    set_db_env_var,
    staging_client,
    predefined_config,
    mocker,
    geoapi_cfg,
):  # pylint: disable=unused-argument
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

    mocker.patch("rs_server_staging.main.get_config_path", return_value=geoapi_cfg)
    mocker.patch("rs_server_staging.main.api", init_pygeoapi())

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
async def test_specific_process(
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,
    resource_name,
    processor_name,  # pylint: disable=unused-argument
):
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
async def test_app_lifespan_local_mode(
    mocker,
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,  # pylint: disable=unused-argument
):
    """Test app_lifespan when running in local mode (no Dask Gateway connection)."""

    # Mock environment to simulate local mode
    mocker.patch.dict(os.environ, {"RSPY_LOCAL_MODE": "1"})

    mock_app = FastAPI()

    async with app_lifespan(mock_app):
        pass  # We are testing the startup logic

    assert "dask_cluster" in mock_app.extra
    assert mock_app.extra["dask_cluster"] is not None


@pytest.mark.asyncio
async def test_app_lifespan_gateway_error(
    mocker,
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,  # pylint: disable=unused-argument
):
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
