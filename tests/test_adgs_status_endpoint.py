"""Unittests for adgs status endpoint."""
from contextlib import contextmanager

import pytest
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import EDownloadStatus


@pytest.mark.unit
def test_adgs_valid_status_request(client):
    """
    Tests the ADGS service's ability to correctly report the status of a download request.

    This unit test verifies that the '/adgs/aux/status' endpoint properly handles requests for download status.
    It checks two scenarios:
    1) When the requested AUX name is not present in the database, expecting a 404 (NOT_FOUND) status code.
    2) When the AUX name is present in the database with a specific status (IN_PROGRESS), expecting a 200 status code
       along with the correct AUX name and status.

    @param client: The FastAPI test client used to send requests to the endpoint.

    Steps:
    - Create the endpoint URL with a predefined AUX name.
    - Initially, send a GET request to check the status of the AUX name that does not exist in the database.
    - Verify that the response status code is 404 (NOT_FOUND).
    - Insert a new entry into the database with the AUX name and status set to 'IN_PROGRESS'.
    - Send another GET request to check the status of the newly inserted AUX name.
    - Verify that the response status code is 200 and the response JSON contains the correct AUX name and status.

    Note:
    - The test uses a context manager to handle database interactions.
    - The EDownloadStatus enumeration is used to specify and check the status values.
    """
    aux_name = "some_aux_name"
    # Create endpoint
    endpoint = f"/adgs/aux/status?name={aux_name}"
    with contextmanager(get_db)() as db:
        # Check status of aux_name
        data = client.get(endpoint)
        # Verify that status is 404 (NOT_FOUND)
        assert data.status_code == 404
        # Insert aux_name into DB with status IN_PROGRESS
        AdgsDownloadStatus.create(
            db=db,
            product_id="id_1",
            name=aux_name,
            available_at_station="2023-12-30T12:00:00.000Z",
            status=EDownloadStatus.IN_PROGRESS,
        )
        # Check status
        data = client.get(endpoint)
        # Verify return status code, aux_name and aux_status
        assert data.status_code == 200
        assert data.json()["name"] == aux_name
        assert EDownloadStatus(data.json()["status"]) == EDownloadStatus.IN_PROGRESS
