"""Test staging module."""

import pytest


@pytest.mark.unit
def test_ping(staging_client):
    """Test status."""
    response = staging_client.get("/_mgmt/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.unit
def test_execute_staging_process(staging_client):
    """Create a job using a post to /processes/staging/execution."""
    response = staging_client.post("/processes/staging/execution", json={"parameters": {"key": "value"}})
    assert response.status_code == 200
    assert "job_id" in response.json()
    assert response.json()["message"] == "Process executed successfully"


@pytest.mark.unit
def test_get_job_status(staging_client):
    """Create a job and get the status."""
    # First, create a job to get its status
    response = staging_client.post("/processes/staging/execution", json={"parameters": {"key": "value"}})
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    # Now, get the status of the created job
    response = staging_client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "job_id" in response.json()
    assert response.json()["job_id"] == job_id
