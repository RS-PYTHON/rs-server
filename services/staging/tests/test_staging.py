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
import copy
import os
from datetime import datetime

import pytest
from fastapi import FastAPI
from pygeoapi.process.base import JobNotFoundError
from rs_server_staging.main import (
    app_lifespan,
    format_job_data,
    format_jobs_data,
    get_config_contents,
    init_db,
    init_pygeoapi,
)
from sqlalchemy.exc import SQLAlchemyError
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

expected_jobs_test = [
    {
        "jobID": "job_1",
        "status": "running",
        "type": "process",
        "progress": 0.0,
        "message": "Test detail",
        "created": datetime(2024, 1, 1, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated": datetime(2024, 1, 1, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "processID": "staging",
    },
    {
        "jobID": "job_2",
        "status": "running",
        "type": "process",
        "progress": 55.0,
        "message": "Test detail",
        "created": datetime(2024, 1, 2, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated": datetime(2024, 1, 2, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "processID": "staging",
    },
    {
        "jobID": "job_3",
        "status": "running",
        "type": "process",
        "progress": 15.0,
        "message": "Test detail",
        "created": datetime(2024, 1, 3, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated": datetime(2024, 1, 3, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "processID": "staging",
    },
    {
        "jobID": "job_4",
        "status": "successful",
        "type": "process",
        "progress": 100.0,
        "message": "Test detail",
        "created": datetime(2024, 1, 4, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated": datetime(2024, 1, 4, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "processID": "staging",
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


def test_format_job_data(mock_jobs):
    """
    Check the behavior of the method that format the output of the job information returned by
    the PostgresSQL database
    """
    # ----- Check that the right exception is raised if the input job data
    # doesn't have the right format
    wrong_mock_job = copy.deepcopy(mock_jobs[0])
    wrong_mock_job["wrong_attribute"] = wrong_mock_job.pop("identifier")
    with pytest.raises(Exception) as excinfo:
        format_job_data(wrong_mock_job)
    assert "attribute 'identifier' is missing" in str(excinfo.value)

    # ----- Check that the input job is well formatted
    mock_job = copy.deepcopy(mock_jobs[0])
    expected_response = expected_jobs_test[0]
    assert format_job_data(mock_job) == expected_response


def test_format_jobs_data(mock_jobs):
    """
    Check the behavior of the method that format the output of the job information returned by
    the PostgresSQL database
    """
    expected_response = {
        "jobs": expected_jobs_test,
        "links": [
            {
                "href": "string",
                "rel": "service",
                "type": "application/json",
                "hreflang": "en",
                "title": "List of jobs",
            },
        ],
    }
    # ----- Check that the right exception is raised if the input jobs is something else than a dictionary
    with pytest.raises(Exception) as excinfo:
        format_jobs_data("wrong_data")  # type: ignore
    assert "Expected a dictionary as input" in str(excinfo.value)

    # ----- Check that the right exception is raised if the input job doesn't have the required 'jobs' attributes
    with pytest.raises(Exception) as excinfo:
        format_jobs_data({"attr1": "val1", "attr2": "val2"})
    assert "Invalid format for input jobs: missing 'jobs' key" in str(excinfo.value)

    # ----- Check that the input job is well formatted if the input has the correct format
    mock_jobs = {
        "jobs": copy.deepcopy(mock_jobs),
        "links": [
            {
                "href": "string",
                "rel": "service",
                "type": "application/json",
                "hreflang": "en",
                "title": "List of jobs",
            },
        ],
    }
    assert format_jobs_data(mock_jobs) == expected_response


@pytest.mark.asyncio
async def test_get_jobs_endpoint(
    mocker,
    mock_app,  # pylint: disable=unused-argument
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,
):
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
    mock_jobs = [
        {
            "identifier": "job_1",
            "status": "successful",
            "type": "process",
            "progress": 100.0,
            "message": "Test detail",
            "created": datetime(2024, 1, 1, 12, 0, 0),
            "updated": datetime(2024, 1, 1, 13, 0, 0),
            "processID": "staging",
        },
        {
            "identifier": "job_2",
            "status": "running",
            "type": "process",
            "progress": 90.25,
            "message": "Test detail",
            "created": datetime(2024, 1, 2, 12, 0, 0),
            "updated": datetime(2024, 1, 2, 13, 0, 0),
            "processID": "staging",
        },
    ]
    mock_jobs_result = [format_job_data(x) for x in mock_jobs]
    links = [
        {"href": "string", "rel": "service", "type": "application/json", "hreflang": "en", "title": "List of jobs"},
    ]
    # ----- Mock app.extra with some jobs from the database mock to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()

    # Simulate postgres returning jobs
    mock_db_table.get_jobs.return_value = {"jobs": mock_jobs, "numberMatched": 2}
    # Patch app.extra with the mock db_table
    # Ensure app.extra contains all necessary attributes at once
    staging_client.app.extra["process_manager"] = mock_db_table

    # Call the API
    response = staging_client.get("/jobs")

    # Assertions
    assert response.status_code == HTTP_200_OK
    # Check if the returned data matches the mocked jobs
    assert response.json() == {"jobs": list(mock_jobs_result), "numberMatched": 2, "links": links}

    # ----- Mock with an empty db
    mock_db_table.get_jobs.return_value = {"jobs": [], "numberMatched": 0}
    # Patch app.extra with the mock db_table
    staging_client.app.extra["process_manager"] = mock_db_table
    response = staging_client.get("/jobs")
    assert response.status_code == HTTP_200_OK
    # Check if the returned data matches 0 jobs
    assert response.json() == {"jobs": [], "numberMatched": 0, "links": links}

    # ----- Check that a validation exception is returned if one of the job from the response doesn't have
    # the required "type" property (and thus is not ogc compliant)
    wrong_ogc_mock_jobs = copy.deepcopy(mock_jobs)
    # Remove required ogc attribute "type"
    wrong_ogc_mock_jobs[0].pop("type")
    mock_db_table.get_jobs.return_value = {"jobs": list(wrong_ogc_mock_jobs), "numberMatched": 2}
    staging_client.app.extra["process_manager"] = mock_db_table
    response = staging_client.get("/jobs")
    assert response.status_code == HTTP_404_NOT_FOUND
    assert "'type' is a required property" in response.json()["detail"]

    # ----- Check that a validation exception is returned if the response doesn't have the required "links" property
    # (and thus is not ogc compliant)
    mock_formatted_jobs = format_jobs_data({"jobs": mock_jobs, "numberMatched": 2})
    mock_formatted_jobs.pop("links")
    mocker.patch("rs_server_staging.main.format_jobs_data", return_value=mock_formatted_jobs)
    staging_client.app.extra["process_manager"] = mock_db_table
    response = staging_client.get("/jobs")
    assert response.status_code == HTTP_404_NOT_FOUND
    assert "'links' is a required property" in response.json()["detail"]

    # ----- Simulate an error response compliant with ogc
    ogc_error_example = {
        "type": "https://developer.mozilla.org/en/docs/Web/HTTP/Reference/Status/404",
        "status": 404,
        "detail": "get_jobs failed",
    }

    mocker.patch("rs_server_staging.main.format_jobs_data", side_effect=Exception("get_jobs failed"))
    response = staging_client.get("/jobs")
    assert response.status_code == HTTP_404_NOT_FOUND
    assert response.json() == ogc_error_example


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job, expected_status, expected_response",
    [
        (
            {"jobID": "non_existing_id"},
            HTTP_404_NOT_FOUND,
            "Job with ID non_existing_id not found",
        ),
        (expected_jobs_test[0], HTTP_500_INTERNAL_SERVER_ERROR, "'type' is a required property"),
        *[(job, HTTP_200_OK, job) for job in expected_jobs_test],
    ],
)
async def test_get_job(
    mocker,
    mock_app,  # pylint: disable=unused-argument
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,
    mock_jobs,
    expected_job,
    expected_status,
    expected_response,
):  # pylint: disable=R0913, R0917
    """
    Test the GET /jobs/{job_id} endpoint for retrieving job details.

    This test verifies that the details of a specific job can be retrieved
    correctly based on its job ID. It checks both the successful retrieval
    of job details and the appropriate handling of non-existing jobs.

    Args:
        mocker: A mocker object used to create mocks and patches for testing.
        staging_client: A test client for making requests to the FastAPI application.
        mock_jobs: Fixture used to mock output of tiny db jobs
        expected_job (dict): The expected job dictionary containing job_id,
            status, progress, and message for the job to be retrieved.
        expected_status: response HTTP status code
        expected_response: response body (JSON object)

    Assertions:
        - Asserts that the response status code is 200 and the returned job
          details match the expected job dictionary when the job exists.
        - Asserts that the response status code is 404 when the job does not exist.
    """
    # Mock app.extra to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()

    # ----- Simulate JobNotFoundError for non-existing jobs (HTTP 404)
    if expected_status == HTTP_404_NOT_FOUND:
        mock_db_table.get_job.side_effect = JobNotFoundError

    # ----- Check that a validation exception is returned if the jobs from the database are
    # not OGC compliant
    elif expected_status == HTTP_500_INTERNAL_SERVER_ERROR:
        wrong_ogc_mock_jobs = copy.deepcopy(mock_jobs)
        # Remove required ogc attribute "type" from all jobs of the get_job output mock
        for job in wrong_ogc_mock_jobs:
            job.pop("type")
        # Remove required ogc attribute "type"
        mock_db_table.get_job.return_value = next(
            job for job in wrong_ogc_mock_jobs if job["identifier"] == expected_job["jobID"]
        )
    # Return an existing job normally (HTTP 200)
    else:
        mock_db_table.get_job.return_value = next(
            job for job in mock_jobs if job["identifier"] == expected_job["jobID"]
        )

    # Ensure app.extra contains all necessary attributes at once
    staging_client.app.extra["process_manager"] = mock_db_table

    # Call the API
    response = staging_client.get(f"/jobs/{expected_job['jobID']}")

    # Assert response status code and content
    assert response.status_code == expected_status

    if expected_status != HTTP_200_OK:
        assert expected_response in response.json()["detail"]
    else:
        assert response.json() == expected_response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job, expected_status, expected_response",
    [
        (
            {"jobID": "non_existing_id"},
            HTTP_404_NOT_FOUND,
            "Job with ID non_existing_id not found",
        ),
        (
            expected_jobs_test[0],
            HTTP_500_INTERNAL_SERVER_ERROR,
            "{'status': 'format'} is not valid under any of the given schemas",
        ),
        *[(job, HTTP_200_OK, job["status"]) for job in expected_jobs_test],
    ],
)
async def test_get_job_result(
    mocker,
    mock_app,  # pylint: disable=unused-argument
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,
    mock_jobs,
    expected_job,
    expected_status,
    expected_response,
):  # pylint: disable=R0913, R0917
    """
    Test the GET /jobs/{job_id}/results endpoint for retrieving job results.

    This test verifies that the results of a specific job can be retrieved
    correctly based on its job ID. It checks both the successful retrieval
    of job results and the appropriate handling of non-existing jobs.

    Args:
        mocker: A mocker object used to create mocks and patches for testing.
        staging_client: A test client for making requests to the FastAPI application.
        mock_jobs: Fixture used to mock output of tiny db jobs
        expected_job (dict): The expected job dictionary containing job_id,
            status, progress, and message for the job whose results are to be retrieved.
        expected_status: response HTTP status code
        expected_response: response body (JSON object)

    Assertions:
        - (
            {"jobID": "non_existing_id"},
            HTTP_404_NOT_FOUND,
            {"detail": "Job with ID non_existing_id not found"},
        ), Asserts that the response status code is 200 and the returned job result
          matches the expected job status when the job exists.
        - Asserts that the response status code is 404 when the job does not exist.
    """
    # Mock app.extra to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()

    # ----- Simulate JobNotFoundError for non-existing jobs (HTTP 404)
    if expected_status == HTTP_404_NOT_FOUND:
        mock_db_table.get_job.side_effect = JobNotFoundError
    # ----- Check that a validation exception is returned if the jobs from the database are
    # not OGC compliant
    elif expected_status == HTTP_500_INTERNAL_SERVER_ERROR:
        wrong_ogc_mock_job = copy.deepcopy(mock_jobs[0])
        wrong_ogc_mock_job["status"] = {"wrong": {"status": "format"}}
        # Remove required ogc attribute "type"
        mock_db_table.get_job.return_value = wrong_ogc_mock_job
    # Return an existing job normally (HTTP 200)
    else:
        mock_db_table.get_job.return_value = next(
            job for job in mock_jobs if job["identifier"] == expected_job["jobID"]
        )

    # Ensure app.extra contains all necessary attributes at once
    staging_client.app.extra["process_manager"] = mock_db_table

    # Call the API
    job_id = expected_job.get("jobID")
    response = staging_client.get(f"/jobs/{job_id}/results")

    # Assert response status code and content
    assert response.status_code == expected_status
    if expected_status != HTTP_200_OK:
        assert expected_response in response.json()["detail"]
    else:
        assert response.json() == expected_response


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "expected_job, expected_status, expected_response",
    [
        ({"jobID": "non_existing_id"}, HTTP_404_NOT_FOUND, "Job with ID non_existing_id not found"),
        (expected_jobs_test[0], HTTP_500_INTERNAL_SERVER_ERROR, "'type' is a required property"),
        *[(job, HTTP_200_OK, f"Job {job['jobID']} deleted successfully") for job in expected_jobs_test],
    ],
)
async def test_delete_job_endpoint(
    mocker,
    mock_app,  # pylint: disable=unused-argument
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,
    mock_jobs,
    expected_job,
    expected_status,
    expected_response,
):  # pylint: disable=R0913, R0917
    """
    Test the DELETE /jobs/{job_id} endpoint for deleting a specific job.

    This test verifies the behavior of the job deletion endpoint by checking
    if the job can be successfully deleted when it exists or if a 404 status
    code is returned when the job does not exist.

    Args:
        mocker: A mocker object used to create mocks and patches for testing.
        staging_client: A test client for making requests to the FastAPI application.
        mock_jobs: Fixture used to mock output of tiny db jobs
        expected_job (dict): The expected job dictionary containing job_id,
            status, progress, and message for the job to be deleted.
        expected_status: response HTTP status code
        expected_response: response body (JSON object)

    Assertions:
        - Asserts that the response status code is 200 if the job is successfully deleted.
        - Asserts that the response status code is 404 if the job does not exist.
        - Asserts that the response status code is 500 if other exception occurs.
    """
    # Mock app.extra to ensure 'db_table' exists
    mock_db_table = mocker.MagicMock()

    # ----- Simulate JobNotFoundError for non-existing jobs (HTTP 404)
    if expected_status == HTTP_404_NOT_FOUND:
        mock_db_table.get_job.side_effect = JobNotFoundError

    # ----- Check that a validation exception is returned if the jobs from the database are
    # not OGC compliant
    elif expected_status == HTTP_500_INTERNAL_SERVER_ERROR:
        wrong_ogc_mock_jobs = copy.deepcopy(mock_jobs)
        # Remove required ogc attribute "type" from all jobs of the get_job output mock
        for job in wrong_ogc_mock_jobs:
            job.pop("type")
        # Remove required ogc attribute "type"
        mock_db_table.get_job.return_value = next(
            job for job in wrong_ogc_mock_jobs if job["identifier"] == expected_job["jobID"]
        )

    # ----- Return an existing job normally (HTTP 200)
    else:
        mock_db_table.get_job.return_value = next(
            job for job in mock_jobs if job["identifier"] == expected_job["jobID"]
        )
        mock_db_table.delete_job.return_value = next(
            job for job in mock_jobs if job["identifier"] == expected_job["jobID"]
        )

    # Ensure app.extra contains all necessary attributes at once
    staging_client.app.extra["process_manager"] = mock_db_table

    # Call the API
    response = staging_client.delete(f"/jobs/{expected_job['jobID']}")

    # Assert response status code and content
    assert response.status_code == expected_status
    if expected_status != HTTP_200_OK:
        assert expected_response in response.json()["detail"]
    else:
        assert response.json()["message"] == expected_response


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
    # ----- Check the behaviour of a response with a correct ogc format
    mocker.patch("rs_server_staging.main.get_config_path", return_value=geoapi_cfg)
    mocker.patch("rs_server_staging.main.api", init_pygeoapi())

    response = staging_client.get("/processes")
    assert response.status_code == HTTP_200_OK
    input_processors = [resource["processor"]["name"] for resource in predefined_config["resources"].values()]
    # Extract processors from the output
    output_processors = [process["id"] for process in response.json()["processes"]]
    # Assert that both lists of processors match
    assert sorted(input_processors) == sorted(output_processors), "Processors do not match!"

    # ----- Mock api.config to send a list of resources with an incorrect format, check that the right
    # validation exception is raised
    mock_resources = {
        "mock_resource_1": {
            "type": "process",
            "processor": {"name": {"wrong_processor_name_format": "wrong_processor_name_format"}},
        },
        "mock_resource_2": {
            "type": "process",
            "processor": {"name": {"wrong_processor_name_format": "wrong_processor_name_format"}},
        },
    }
    mocker.patch.dict("rs_server_staging.main.api.config", {"resources": mock_resources})
    response = staging_client.get("/processes")
    assert response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert "is not of type 'string'" in response.json()["detail"]


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
@pytest.mark.parametrize(
    "valid_staging_body, wrong_staging_body",
    [
        (
            {
                "inputs": {
                    "collection": "Target collection",
                    "items": {"value": {"type": "FeatureCollection", "features": [], "links": []}},
                },
            },
            {
                "inputs": {
                    "collection": "Target collection",
                    "items": {"value": {"type": "FeatureCollection", "features": "wrong_format", "links": []}},
                },
            },
        ),
        (
            {
                "inputs": {
                    "collection": "Target collection",
                    "items": {
                        "href": (
                            "http://localhost:8002/cadip/search?"
                            "ids=S1A_20231120061537234567&collections=cadip_sentinel1"
                        ),
                    },
                },
            },
            {
                "inputs": {
                    "collection": "Target collection",
                    "items": {
                        "href": {"id": "this dict shouldn't exist"},
                    },
                },
            },
        ),
    ],
)
async def test_execute_staging(
    mocker,
    mock_app,  # pylint: disable=unused-argument
    mock_jobs,
    staging_client,
    valid_staging_body,
    wrong_staging_body,
):
    """Test to run the /processes/{resource}/execution endpoint"""
    resource_name = "staging"
    # ----- Test case where we have a staging body uncompliant with ogc
    response = staging_client.post(f"/processes/{resource_name}/execution", json=wrong_staging_body)
    assert response.status_code == HTTP_422_UNPROCESSABLE_ENTITY

    mock_db_table = mocker.MagicMock()
    mocker.patch("rs_server_staging.processors.Staging.execute", return_value=(None, {"running": "mock_job_id"}))

    # ----- Test case where both staging body and response are compliant with ogc
    mock_db_table.get_job.return_value = next(
        job for job in mock_jobs if job["identifier"] == expected_jobs_test[0]["jobID"]
    )
    # Patch app.extra with the mock db_table
    staging_client.app.extra["process_manager"] = mock_db_table
    staging_client.app.extra["dask_cluster"] = None
    response = staging_client.post(f"/processes/{resource_name}/execution", json=valid_staging_body)
    assert response.status_code == HTTP_201_CREATED
    assert response.json() == expected_jobs_test[0]

    # ----- Test case where we have a staging response which is uncompliant with ogc
    wrong_ogc_mock_jobs = copy.deepcopy(mock_jobs)
    # Remove required ogc attribute "type" from all jobs of the get_job output mock
    for job in wrong_ogc_mock_jobs:
        job.pop("type")
    # Remove required ogc attribute "type"
    mock_db_table.get_job.return_value = next(
        job for job in wrong_ogc_mock_jobs if job["identifier"] == expected_jobs_test[0]["jobID"]
    )
    staging_client.app.extra["process_manager"] = mock_db_table
    response = staging_client.post(f"/processes/{resource_name}/execution", json=valid_staging_body)
    assert response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert "'type' is a required property" in response.json()


@pytest.mark.asyncio
async def test_app_lifespan_local_mode(
    set_db_env_var,  # pylint: disable=unused-argument
    staging_client,  # pylint: disable=unused-argument
):
    """Test app_lifespan when running in local mode (no Dask Gateway connection)."""
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
    mocker.patch("rs_server_common.settings.LOCAL_MODE", new=False, autospec=False)
    mocker.patch("rs_server_common.settings.CLUSTER_MODE", new=True, autospec=False)

    # Mock FastAPI app
    mock_app = FastAPI()

    async with app_lifespan(mock_app):
        pass  # We are testing the startup logic

    assert "dask_cluster" in mock_app.extra
    assert mock_app.extra["dask_cluster"] is None
