"""Module used to test CADIP download endpoint"""
import filecmp
import os
import os.path as osp
import tempfile
import time
from contextlib import contextmanager

import pytest
import responses
from rs_server_cadip.cadu_download_status import CaduDownloadStatus, EDownloadStatus
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.db.database import get_db

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
def test_valid_endpoint_request_download(client):  # pylint: disable=unused-argument
    """Test the behavior of a valid endpoint request for CADIP CADU download.

    This unit test checks the behavior of the CADIP CADU download endpoint when provided with
    valid parameters. It simulates the download process, verifies the status code, and checks
    the content of the downloaded file.

    Args:
        client: The client fixture for the test.

    Returns:
        None

    Raises:
        AssertionError: If the test fails to assert the expected outcomes.
    """
    filename = "CADIP_test_file_eodag.raw"
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    with tempfile.TemporaryDirectory() as download_dir, contextmanager(get_db)() as db:
        endpoint = f"/cadip/CADIP/cadu?product_id=id_1&name={filename}&local={download_dir}"
        # Add a download status to database

        CaduDownloadStatus.create(
            db=db,
            product_id=product_id,
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
        # send the request
        data = client.get(endpoint)

        # let the file to be copied local
        time.sleep(1)
        assert data.status_code == 200
        assert data.json() == {"started": "true"}
        # test file content
        assert filecmp.cmp(
            os.path.join(download_dir, filename),
            os.path.join(ENDPOINTS_FOLDER, "CADIP_test_file.raw"),
        )


@pytest.mark.unit
def test_invalid_endpoint_request(mocker, client):
    """
    Test the system's response to an invalid request made to the CADIP download endpoint.

    This unit test examines how the system responds when an invalid request is made to the CADIP
    download endpoint. It specifically addresses the scenario where the database operation to
    retrieve or create a CADU download status entry fails, simulating a database access issue.
    The test ensures that in such cases, the system responds appropriately with the correct HTTP
    status code and message, indicating that the download process has not started.

    Test Steps:
    1. Mock the `CaduDownloadStatus.create` method to return None, simulating a failure in
       database operations.
    2. Make a GET request to the endpoint with an invalid CADU ID and filename.
    3. Verify that the mocked database operation is called and returns None.
    4. Check that the HTTP response correctly indicates that the download has not started.
    5. Confirm that the HTTP status code is 503, indicating a service unavailable error due to
       database issues.

    Args:
        mocker (fixture): A pytest-mock fixture used for mocking dependencies.
        client (fixture): A pytest fixture to provide a FastAPI client.

    Returns:
        None: This test does not return anything but asserts conditions related to the system's
              response to invalid endpoint requests.
    """
    filename = "Invalid_name"
    product_id = "invalid_ID"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"/cadip/CADIP/cadu?product_id=id_1&name={filename}"

    with contextmanager(get_db)() as db:
        # Add a download status to database
        # Mock a problem while getting / creating db entry
        mocker.patch(
            "rs_server_cadip.cadu_download_status.CaduDownloadStatus.create",
            return_value=None,
        )
        result = CaduDownloadStatus.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.IN_PROGRESS,
        )
        # Check patch
        assert result is None
        # send the request
        data = client.get(endpoint)
        # Verify that download has not started.
        # 503 - 503 Service Unavailable -> Meaning db issue.
        assert data.status_code == 503
        assert data.json() == {"started": "false"}


@pytest.mark.unit
def test_eodag_provider_failure_while_creating_provider(mocker, client):
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
        client (fixture): A pytest fixture to provide a FastAPI client.

    Returns:
        None: This test does not return anything but asserts conditions related to the system's
              response to EODAG provider creation failure.
    """
    filename = "CADIP_test_file_eodag.raw"
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"/cadip/CADIP/cadu?product_id=id_1&name={filename}"
    with contextmanager(get_db)() as db:
        # Init this product into db, set the status to NOT_STARTED
        CaduDownloadStatus.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.NOT_STARTED,
        )
        # Mock function rs_server.CADIP.api.cadu_download.init_cadip_data_retriever to raise an error
        # In order to verify that download status is not set to in progress and set to false.
        mocker.patch(
            "rs_server.CADIP.api.cadu_download.init_cadip_data_retriever",
            side_effect=CreateProviderFailed("Invalid station"),
        )
        # send the request
        data = client.get(endpoint)
        # After endpoint process this download request, check the db status
        result = CaduDownloadStatus.get(db=db, name=filename)
        # DB Status is set to failed
        assert result.status == EDownloadStatus.FAILED
        assert data.json() == {"started": "false"}


@pytest.mark.unit
def test_eodag_provider_failure_while_downloading(mocker, client):
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
        client (fixture): A pytest fixture to provide a FastAPI client.

    Returns:
        None: This function does not return a value. It asserts various conditions to ensure proper error
        handling in the download process.
    """
    filename = "CADIP_test_file_eodag.raw"
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"
    endpoint = f"/cadip/CADIP/cadu?product_id=id_1&name={filename}"
    with contextmanager(get_db)() as db:
        # Init this product into db, set the status to NOT_STARTED
        CaduDownloadStatus.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.NOT_STARTED,
        )
        # Mock function data_retriever.download to raise an error
        # In order to verify that download status is not set to in progress and set to false.
        mocker.patch(
            "rs_server_common.data_retrieval.data_retriever.DataRetriever.download",
            side_effect=Exception("Some Runtime Error occured here."),
        )
        # send the request
        data = client.get(endpoint)
        # After endpoint process this download request, check the db status
        result = CaduDownloadStatus.get(db=db, name=filename)
        # DB Status is set to failed and download started
        # Error message is written into db
        assert result.status == EDownloadStatus.FAILED
        assert data.json() == {"started": "true"}
        assert result.status_fail_message == "Exception('Some Runtime Error occured here.')"


@pytest.mark.unit
@responses.activate
def test_failure_while_uploading_to_bucket(mocker, monkeypatch, client):
    """
    Test the systems behavior when there is a failure during the upload process to the S3 bucket.

    This unit test simulates a scenario where a runtime error occurs during the initialization of
    the S3StorageHandler, which is responsible for handling the upload process to an S3 bucket. The
    test ensures that in such cases, the system correctly updates the CADU download status to FAILED
    in the database and responds with an HTTP status code of 200, indicating that the request was
    processed but the upload failed.

    Steps:
    1. Mock environment variables related to S3 connection details.
    2. Simulate the retrieval of a CADIP file-stream from a mock endpoint.
    3. Insert a product into the database with a status of NOT_STARTED.
    4. Verify the inserted product's status is NOT_STARTED.
    5. Mock S3StorageHandler to raise a RuntimeError upon initialization.
    6. Make a GET request to the specified endpoint.
    7. Allow time for the byte-stream to start and attempt a write locally.
    8. Retrieve the product status from the database after the endpoint call.
    9. Verify that the product status in the database is updated to FAILED.
    10. Assert that the response's HTTP status code is 200.

    Args:
        mocker (pytest.Mock): Pytest mock object to mock certain behaviors.
        monkeypatch (pytest.MonkeyPatch): Pytest object for patching module and environment variables.
        client (TestClient): Test client for making API requests.

    Returns:
        None: The function asserts conditions but does not return any value.
    """
    filename = "CADIP_test_file_eodag.raw"
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"
    obs = "s3://some_bucket_info"
    endpoint = f"/cadip/CADIP/cadu?product_id=id_1&name={filename}&obs={obs}"
    # Mock os environ s3 connection details
    monkeypatch.setenv("S3_ENDPOINT", "mock_endpoint")
    monkeypatch.setenv("S3_ACCESSKEY", "mock_accesskey")
    monkeypatch.setenv("S3_SECRETKEY", "mock_secretkey")

    with contextmanager(get_db)() as db:
        # Simulate CADIP file-stream download
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Files(id_1)/$value",
            body="some byte-array data\n",
            status=200,
        )
        # Init this product into db, set the status to NOT_STARTED
        CaduDownloadStatus.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.NOT_STARTED,
        )
        # Check that product we just inserted into db is not_started
        result = CaduDownloadStatus.get(db=db, name=filename)
        assert result.status == EDownloadStatus.NOT_STARTED
        # bypass S3StorageHandler object by raising a RunTimeError
        mocker.patch(
            "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.__init__",
            return_value=None,
            side_effect=RuntimeError,
        )
        # call the endpoint
        data = client.get(endpoint)
        # Wait in order to start byte-stream and write local
        time.sleep(1)
        # get the product status from db (It should be updated by the endpoint call)
        result = CaduDownloadStatus.get(db=db, name=filename)
        # Check that update_db function set the status to FAILED
        assert result.status == EDownloadStatus.FAILED
        assert data.status_code == 200
