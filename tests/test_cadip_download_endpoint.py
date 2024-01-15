"""Docstring to be added."""
import filecmp
import os
import os.path as osp
import time
from contextlib import contextmanager

import pytest
import responses
from fastapi.testclient import TestClient

from rs_server.CADIP.cadip_backend import app
from rs_server.CADIP.models.cadu_download_status import (
    CaduDownloadStatus,
    EDownloadStatus,
)
from rs_server.db.database import get_db
from services.common.rs_server_common.data_retrieval.provider import (
    CreateProviderFailed,
)

# Resource folders specified from the parent directory of this current script
RSC_FOLDER = osp.realpath(osp.join(osp.dirname(__file__), "resources"))
S3_FOLDER = osp.join(RSC_FOLDER, "s3")
ENDPOINTS_FOLDER = osp.join(RSC_FOLDER, "endpoints")

"""
TC-001 : User1 sends a CURL request to a CADIP backend Server on
URL /cadip/{station}/cadu?name=”xxx”&local="pathXXXX". He receives a download start status.
The download continues in background. After few minutes, the file is stored on the local disk.'
"""


@pytest.mark.unit
@responses.activate
def test_valid_endpoint_request(database):  # pylint: disable=unused-argument
    """Test the behavior of a valid endpoint request for CADIP CADU download.

    This unit test checks the behavior of the CADIP CADU download endpoint when provided with
    valid parameters. It simulates the download process, verifies the status code, and checks
    the content of the downloaded file.

    Args:
        database: The database fixture for the test.

    Returns:
        None

    Raises:
        AssertionError: If the test fails to assert the expected outcomes.
    """
    download_dir = "/tmp"
    filename = "CADIP_test_file_eodag.raw"
    cadu_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"/cadip/CADIP/cadu?cadu_id=id_1&name={filename}"

    with contextmanager(get_db)() as db:
        # Add a download status to database
        CaduDownloadStatus.get_or_create(
            db=db,
            cadu_id=cadu_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.IN_PROGRESS,
        )
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Files(id_1)/$value",
            body="some byte-array data\n",
            status=200,
        )
        client = TestClient(app)
        # send the request
        data = client.get(endpoint)
        # let the file to be copied local
        time.sleep(1)
        try:
            assert data.status_code == 200
            assert data.json() == {"started": "true"}
            # test file content
            assert filecmp.cmp(
                os.path.join(download_dir, filename),
                os.path.join(ENDPOINTS_FOLDER, "CADIP_test_file.raw"),
            )
            # clean downloaded file
        finally:
            os.remove(os.path.join(download_dir, filename))


@pytest.mark.unit
def test_invalid_endpoint_request(mocker, database):  # pylint: disable=unused-argument
    """
    Test the system's response to an invalid request made to the CADIP download endpoint.

    This unit test examines how the system responds when an invalid request is made to the CADIP
    download endpoint. It specifically addresses the scenario where the database operation to
    retrieve or create a CADU download status entry fails, simulating a database access issue.
    The test ensures that in such cases, the system responds appropriately with the correct HTTP
    status code and message, indicating that the download process has not started.

    Test Steps:
    1. Mock the `CaduDownloadStatus.get_or_create` method to return None, simulating a failure in
       database operations.
    2. Make a GET request to the endpoint with an invalid CADU ID and filename.
    3. Verify that the mocked database operation is called and returns None.
    4. Check that the HTTP response correctly indicates that the download has not started.
    5. Confirm that the HTTP status code is 503, indicating a service unavailable error due to
       database issues.

    Args:
        mocker (fixture): A pytest-mock fixture used for mocking dependencies.
        database (fixture): A pytest fixture that provides access to the database for test setup
                           and verification.

    Returns:
        None: This test does not return anything but asserts conditions related to the system's
              response to invalid endpoint requests.
    """
    filename = "Invalid_name"
    cadu_id = "invalid_ID"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"/cadip/CADIP/cadu?cadu_id=id_1&name={filename}"

    with contextmanager(get_db)() as db:
        # Add a download status to database
        # Mock a problem while getting / creating db entry
        mocker.patch(
            "rs_server.CADIP.models.cadu_download_status.CaduDownloadStatus.get_or_create",
            return_value=None,
        )
        result = CaduDownloadStatus.get_or_create(
            db=db,
            cadu_id=cadu_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.IN_PROGRESS,
        )
        # Check patch
        assert result is None
        client = TestClient(app)
        # send the request
        data = client.get(endpoint)
        # Verify that download has not started.
        # 503 - 503 Service Unavailable -> Meaning db issue.
        assert data.status_code == 503
        assert data.json() == {"started": "false"}


@pytest.mark.unit
def test_eodag_provider_failure_while_creating_provider(mocker, database):  # pylint: disable=unused-argument
    """
    Test the system response to an error during EODAG provider creation.

    This unit test evaluates the behavior of the system when an error occurs during the creation of
    the EODAG provider in the CADU download endpoint. It specifically tests the scenario where the
    `init_cadip_data_retriever` function raises a `CreateProviderFailed` exception. The test aims
    to ensure that, in such cases, the system responds appropriately with the correct HTTP status
    code and message, indicating that the download process has not started.

    Test Steps:
    1. Mock the `init_cadip_data_retriever` function to raise a `CreateProviderFailed` exception,
       simulating an error during the creation of the EODAG provider.
    2. Make a GET request to the endpoint with a valid CADU ID and filename.
    3. Verify that the mocked provider creation function is called and raises the expected exception.
    4. Check that the HTTP response correctly indicates that the download has not started.
    5. Confirm that the HTTP status code is 503, indicating a service unavailable error due to the
       provider creation failure.

    Args:
        mocker (fixture): A pytest-mock fixture used for mocking dependencies.
        database (fixture): A pytest fixture that provides access to the database for test setup
                           and verification.

    Returns:
        None: This test does not return anything but asserts conditions related to the system's
              response to EODAG provider creation failure.
    """
    filename = "CADIP_test_file_eodag.raw"
    cadu_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"/cadip/CADIP/cadu?cadu_id=id_1&name={filename}"
    with contextmanager(get_db)() as db:
        # Init this product into db, set the status to NOT_STARTED
        CaduDownloadStatus.get_or_create(
            db=db,
            cadu_id=cadu_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.NOT_STARTED,
        )
        client = TestClient(app)
        # Mock function rs_server.CADIP.api.cadu_download.init_cadip_data_retriever to raise an error
        # In order to verify that download status is not set to in progress and set to false.
        mocker.patch(
            "rs_server.CADIP.api.cadu_download.init_cadip_data_retriever",
            side_effect=CreateProviderFailed("Invalid station"),
        )
        # send the request
        data = client.get(endpoint)
        # After endpoint process this download request, check the db status
        result = CaduDownloadStatus.get_or_create(
            db=db,
            cadu_id=cadu_id,
            name=filename,
            available_at_station=publication_date,
        )
        # DB Status is set to failed
        assert result.status == EDownloadStatus.FAILED
        assert data.json() == {"started": "false"}


@pytest.mark.unit
def test_eodag_provider_failure_while_downloading(mocker, database):  # pylint: disable=unused-argument
    """
    Test the EODAG providers error handling during a download failure.

    This unit test aims to validate the robustness of the EODAG provider's download mechanism.
    It specifically tests the system's response when an unexpected error occurs during the file download process.
    The test ensures that in the event of such a failure, the system correctly updates the CADU download status
    to FAILED in the database.
    Additionally, it checks that the appropriate HTTP response is returned to indicate the initiation of the download
    process despite the encountered error.

    The test scenario is as follows:
    1. A CADU product is initialized in the database with a status of NOT_STARTED.
    2. The `DataRetriever.download` method is mocked to trigger a runtime exception, simulating a download failure.
    3. A GET request is sent to the download endpoint, invoking the download process.
    4. The test verifies that the CADU download status in the database is updated to FAILED as a result of the
        simulated error.
    5. The test confirms that the HTTP response correctly indicates the initiation of the download process,
        despite the error.
    6. Finally, it checks that the database correctly logs the reason for the download failure.

    Args:
        mocker (fixture): A pytest-mock fixture used for mocking dependencies.
        database (fixture): A pytest fixture that provides access to the database for test setup and verification.

    Returns:
        None: This function does not return a value. It asserts various conditions to ensure proper error
        handling in the download process.
    """
    filename = "CADIP_test_file_eodag.raw"
    cadu_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"
    endpoint = f"/cadip/CADIP/cadu?cadu_id=id_1&name={filename}"
    with contextmanager(get_db)() as db:
        # Init this product into db, set the status to NOT_STARTED
        CaduDownloadStatus.get_or_create(
            db=db,
            cadu_id=cadu_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.NOT_STARTED,
        )
        client = TestClient(app)
        # Mock function data_retriever.download to raise an error
        # In order to verify that download status is not set to in progress and set to false.
        mocker.patch(
            "services.common.rs_server_common.data_retrieval.data_retriever.DataRetriever.download",
            side_effect=Exception("Some Runtime Error occured here."),
        )
        # send the request
        data = client.get(endpoint)
        # After endpoint process this download request, check the db status
        result = CaduDownloadStatus.get_or_create(
            db=db,
            cadu_id=cadu_id,
            name=filename,
            available_at_station=publication_date,
        )
        # DB Status is set to failed and download started
        # Error message is written into db
        assert result.status == EDownloadStatus.FAILED
        assert data.json() == {"started": "true"}
        assert result.status_fail_message == "Exception('Some Runtime Error occured here.')"
