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

"""Test various data related functions."""

import copy
import os

import pytest
from rs_server_staging.main import (
    format_job_data,
    format_jobs_data,
    get_config_contents,
    init_db,
    init_pygeoapi,
)
from sqlalchemy.exc import SQLAlchemyError

from .conftest import EXPECTED_JOBS_TEST


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
            driver_name="postgresql+psycopg2",
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
    expected_response = EXPECTED_JOBS_TEST[0]
    assert format_job_data(mock_job) == expected_response


def test_format_jobs_data(mock_jobs):
    """
    Check the behavior of the method that format the output of the job information returned by
    the PostgresSQL database
    """
    expected_response = {
        "jobs": EXPECTED_JOBS_TEST,
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
