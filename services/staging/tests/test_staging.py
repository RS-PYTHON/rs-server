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

import pytest
from starlette.status import HTTP_200_OK, HTTP_404_NOT_FOUND


@pytest.mark.unit
def test_ping(staging_client):
    """Test status."""
    response = staging_client.get("/_mgmt/ping")
    assert response.status_code == HTTP_200_OK


@pytest.mark.unit
def test_execute_staging_process(staging_client):
    """Create a job using a post to /processes/staging/execution."""
    response = staging_client.post("/processes/staging/execution", json={"parameters": {"key": "value"}})
    assert response.status_code == HTTP_200_OK
    assert "job_id" in response.json()
    assert response.json()["message"] == "Process executed successfully"


@pytest.mark.unit
def test_execute_wrong_resource(staging_client):
    """Test /processes/{resource_id}/execution."""
    resp = staging_client.post("/processes/unknown_resource/execution", json={"parameters": {"key": "value"}})
    assert resp.status_code == HTTP_404_NOT_FOUND


@pytest.mark.unit
def test_get_job_status(staging_client):
    """Create a job and get the status."""
    # First, create a job to get its status
    response = staging_client.post("/processes/staging/execution", json={"parameters": {"key": "value"}})
    assert response.status_code == HTTP_200_OK
    job_id = response.json()["job_id"]

    # Now, get the status of the created job
    response = staging_client.get(f"/jobs/{job_id}")
    assert response.status_code == HTTP_200_OK
    assert "job_id" in response.json()
    assert response.json()["job_id"] == job_id


@pytest.mark.unit
def test_get_incorrect_job(staging_client):
    """Test /jobs/{job-id}."""
    assert staging_client.get("/jobs/incorrect_job_id").status_code == HTTP_404_NOT_FOUND


# not implemented endpoints tests


@pytest.mark.unit
def test_get_processes(staging_client):
    """Test /processes."""
    assert staging_client.get("/processes").status_code == HTTP_200_OK


@pytest.mark.unit
def test_get_process_resource(staging_client):
    """Test /processes/{resource_id}."""
    assert staging_client.get("/processes/resource_id").status_code == HTTP_200_OK


@pytest.mark.unit
def test_get_jobs(staging_client):
    """Test /jobs."""
    assert staging_client.get("/jobs").status_code == HTTP_200_OK
