"""Unittests for CADU status endpoint."""
from contextlib import contextmanager

import pytest
from rs_server_cadip.cadu_download_status import CaduDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import EDownloadStatus


@pytest.mark.unit
def test_cadip_valid_status_request(client):
    """
    Test the endpoint for retrieving the status of an download from CADIP station.

    This test ensures that the endpoint returns the correct status code and information
    when querying the status of a CADU file. It covers scenarios where
    the file is not found initially (status code 404) and after inserting the file into the
    database with an IN_PROGRESS status, verifying a successful response (status code 200)
    with the correct file name and status.

    Parameters:
    - client: FastAPI test client used for making HTTP requests.

    Steps:
    1. Create the endpoint for querying the status with a specific file name.
    2. Attempt to retrieve the status initially to verify a NOT_FOUND response (status code 404).
    3. Insert a sample CADU file into the database with an IN_PROGRESS status.
    4. Query the status again and verify a successful response (status code 200).
    5. Check that the returned JSON contains the expected file name and an IN_PROGRESS status.

    """
    cadu_name = "some_cadu_file_name.raw"
    cadu_station = "CADIP"
    # Create endpoint
    endpoint = f"/cadip/{cadu_station}/cadu/status?name={cadu_name}"
    with contextmanager(get_db)() as db:
        # Check status of aux_name
        data = client.get(endpoint)
        # Verify that status is 404 (NOT_FOUND)
        assert data.status_code == 404
        # Insert aux_name into DB with status IN_PROGRESS
        CaduDownloadStatus.create(
            db=db,
            product_id="id_1",
            name=cadu_name,
            available_at_station="2023-12-30T12:00:00.000Z",
            status=EDownloadStatus.IN_PROGRESS,
        )
        # Check status
        data = client.get(endpoint)
        # Verify return status code, aux_name and aux_status
        assert data.status_code == 200
        assert data.json()["name"] == cadu_name
        assert EDownloadStatus(data.json()["status"]) == EDownloadStatus.IN_PROGRESS
