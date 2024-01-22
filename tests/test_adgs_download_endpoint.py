"""Module used to test ADGS download endpoint"""
import filecmp
import os
import os.path as osp
import tempfile
import time
from contextlib import contextmanager

import pytest
import responses
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import EDownloadStatus

# Resource folders specified from the parent directory of this current script
RSC_FOLDER = osp.realpath(osp.join(osp.dirname(__file__), "resources"))
S3_FOLDER = osp.join(RSC_FOLDER, "s3")
ENDPOINTS_FOLDER = osp.join(RSC_FOLDER, "endpoints")


@pytest.mark.unit
@responses.activate
def test_valid_endpoint_request_download(client):  # pylint: disable=unused-argument
    """Test the behavior of a valid endpoint request for ADGS AUX download.

    This unit test checks the behavior of the ADGS download endpoint when provided with
    valid parameters. It simulates the download process, verifies the status code, and checks
    the content of the downloaded file.

    Args:
        client: The client fixture for the test.

    Returns:
        None

    Raises:
        AssertionError: If the test fails to assert the expected outcomes.
    """
    filename = "AUX_test_file_eodag.raw"
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    with tempfile.TemporaryDirectory() as download_dir, contextmanager(get_db)() as db:
        # Add a download status to database
        endpoint = f"/adgs/aux?name={filename}&local={download_dir}"
        AdgsDownloadStatus.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            # FIXME
            status=EDownloadStatus.IN_PROGRESS,
        )
        responses.add(
            responses.GET,
            "http://127.0.0.1:5001/Products(id_1)/$value",
            body="some byte-array data\n",
            status=200,
        )
        # send the request
        data = client.get(endpoint)

        # let the file to be copied local
        time.sleep(1)
        assert data.status_code == 200
        assert data.json() == {"started": "true"}
        # test file content
        assert filecmp.cmp(
            os.path.join(download_dir, filename),
            os.path.join(ENDPOINTS_FOLDER, "AUX_test_file.raw"),
        )


@pytest.mark.unit
@responses.activate
def test_exception_while_valid_download(mocker, client):
    """
    Tests the handling of an exception during the download of an ADGS product.

    This unit test simulates a scenario where an exception occurs during the download of an ADGS product,
    specifically when the 'DataRetriever.download' method is called. It ensures that the application handles
    the exception appropriately, updates the database status accordingly, and captures the exception message.

    @param mocker: The pytest-mock fixture for mocking dependencies.
    @param client: The FastAPI test client for making HTTP requests.

    - Sets up the initial state in the database by creating an ADGS download entry with 'IN_PROGRESS' status.
    - Adds a mocked response for a GET request to an external service with a predefined product data.
    - Mocks the 'DataRetriever.download' method to raise an exception during the download process.
    - Asserts the initial status of the download in the database is 'IN_PROGRESS'.
    - Sends a GET request to the '/adgs/aux' endpoint for the download.
    - Asserts that the download status in the database changes to 'FAILED' after encountering the exception.
    - Captures the exception message in the 'status_fail_message' field in the database.

    Note:
    - The mock responses and patches are used to simulate the external service and control the behavior of the download.
    """
    filename = "AUX_test_file_eodag.raw"
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"/adgs/aux?name={filename}"

    with contextmanager(get_db)() as db:
        AdgsDownloadStatus.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.IN_PROGRESS,
        )
        responses.add(
            responses.GET,
            "http://127.0.0.1:5001/Products(id_1)/$value",
            body="some byte-array data\n",
            status=200,
        )
        # Raise an exception while downloading
        mocker.patch(
            "rs_server_common.data_retrieval.data_retriever.DataRetriever.download",
            side_effect=Exception("Error while downloading"),
        )
        # send the request
        assert AdgsDownloadStatus.get(db, name=filename).status == EDownloadStatus.IN_PROGRESS
        client.get(endpoint)
        assert AdgsDownloadStatus.get(db, name=filename).status == EDownloadStatus.FAILED
        assert AdgsDownloadStatus.get(db, name=filename).status_fail_message == "Exception('Error while downloading')"
