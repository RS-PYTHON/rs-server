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
from rs_server_cadip.cadu_download_status import CaduDownloadStatus
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import EDownloadStatus

# Resource folders specified from the parent directory of this current script
RSC_FOLDER = osp.realpath(osp.join(osp.dirname(__file__), "resources"))
S3_FOLDER = osp.join(RSC_FOLDER, "s3")
ENDPOINTS_FOLDER = osp.join(RSC_FOLDER, "endpoints")


# pylint: disable=too-many-arguments
@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize(
    "endpoint, filename, target_filename, db_handler",
    [
        ("/adgs/aux", "AUX_test_file_eodag.raw", "AUX_test_file.raw", AdgsDownloadStatus),
        ("/cadip/CADIP/cadu", "CADIP_test_file_eodag.raw", "CADIP_test_file.raw", CaduDownloadStatus),
    ],
)
def test_valid_endpoint_request_download(
    client,
    endpoint,
    filename,
    target_filename,
    db_handler,
):  # pylint: disable=unused-argument
    """Test the behavior of a valid endpoint request for ADGS AUX / CADIP CADU download.

    This unit test checks the behavior of the ADGS / CADIP download endpoint when provided with
    valid parameters. It simulates the download process, verifies the status code, and checks
    the content of the downloaded file.

    Args:
        client: The client fixture for the test.

    Returns:
        None

    Raises:
        AssertionError: If the test fails to assert the expected outcomes.
    """
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"
    # Add cadip mock server response to eodag download request
    responses.add(
        responses.GET,
        "http://127.0.0.1:5000/Files(id_1)/$value",
        body="some byte-array data\n",
        status=200,
    )
    # Add adgs mock server response to eodag download request
    responses.add(
        responses.GET,
        "http://127.0.0.1:5001/Products(id_1)/$value",
        body="some byte-array data\n",
        status=200,
    )

    with tempfile.TemporaryDirectory() as download_dir, contextmanager(get_db)() as db:
        # Add a download status to database
        endpoint = f"{endpoint}?name={filename}&local={download_dir}"
        db_handler.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            # FIXME
            status=EDownloadStatus.IN_PROGRESS,
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
            os.path.join(ENDPOINTS_FOLDER, target_filename),
        )


@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize(
    "endpoint, filename, db_handler",
    [
        ("/adgs/aux", "AUX_test_file_eodag.raw", AdgsDownloadStatus),
        ("/cadip/CADIP/cadu", "CADIP_test_file_eodag.raw", CaduDownloadStatus),
    ],
)
def test_exception_while_valid_download(
    mocker,
    client,
    endpoint,
    filename,
    db_handler,
):  # pylint: disable=unused-argument
    """
    Tests the handling of an exception during the download of an ADGS / CADIP product.

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
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"{endpoint}?name={filename}"

    with contextmanager(get_db)() as db:
        db_handler.create(
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
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Files(id_1)/$value",
            body="some byte-array data\n",
            status=200,
        )
        # Raise an exception while downloading
        mocker.patch(
            "rs_server_common.data_retrieval.data_retriever.DataRetriever.download",
            side_effect=Exception("Error while downloading"),
        )
        # send the request
        assert db_handler.get(db, name=filename).status == EDownloadStatus.IN_PROGRESS
        client.get(endpoint)
        assert db_handler.get(db, name=filename).status == EDownloadStatus.FAILED
        assert db_handler.get(db, name=filename).status_fail_message == "Exception('Error while downloading')"


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, db_handler",
    [
        ("/adgs/aux", AdgsDownloadStatus),
        ("/cadip/CADIP/cadu", CaduDownloadStatus),
    ],
)
def test_invalid_endpoint_request(mocker, client, endpoint, db_handler):
    """
    Test the system's response to an invalid request made to the ADGS/CADIP download endpoint.

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

    endpoint = f"{endpoint}?product_id=id_1&name={filename}"

    with contextmanager(get_db)() as db:
        # Add a download status to database
        # Mock a problem while getting / creating db entry
        mocker.patch(
            "rs_server_cadip.cadu_download_status.CaduDownloadStatus.create",
            return_value=None,
        )
        mocker.patch(
            "rs_server_adgs.adgs_download_status.AdgsDownloadStatus.create",
            return_value=None,
        )
        result = db_handler.create(
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
@pytest.mark.parametrize(
    "endpoint, filename, db_handler",
    [
        ("/adgs/aux", "ADGS_test_file_eodag.raw", AdgsDownloadStatus),
        ("/cadip/CADIP/cadu", "CADIP_test_file_eodag.raw", CaduDownloadStatus),
    ],
)
def test_eodag_provider_failure_while_creating_provider(mocker, client, endpoint, filename, db_handler):
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
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"{endpoint}?product_id=id_1&name={filename}"
    with contextmanager(get_db)() as db:
        # Init this product into db, set the status to NOT_STARTED
        db_handler.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.NOT_STARTED,
        )
        result = db_handler.get(db=db, name=filename)
        assert result.status == EDownloadStatus.NOT_STARTED
        # Mock function rs_server.CADIP.api.cadu_download.init_cadip_data_retriever to raise an error
        # In order to verify that download status is not set to in progress and set to false.
        mocker.patch(
            "rs_server.CADIP.api.cadu_download.init_cadip_data_retriever",
            side_effect=CreateProviderFailed("Invalid station"),
        )
        mocker.patch(
            "rs_server.ADGS.api.adgs_download.init_adgs_retriever",
            side_effect=CreateProviderFailed("Invalid station"),
        )
        # send the request
        data = client.get(endpoint)
        # After endpoint process this download request, check the db status
        result = db_handler.get(db=db, name=filename)
        # DB Status is set to failed
        assert result.status == EDownloadStatus.FAILED
        assert data.json() == {"started": "false"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, filename, db_handler",
    [
        ("/adgs/aux", "ADGS_test_file_eodag.raw", AdgsDownloadStatus),
        ("/cadip/CADIP/cadu", "CADIP_test_file_eodag.raw", CaduDownloadStatus),
    ],
)
def test_eodag_provider_failure_while_downloading(mocker, client, endpoint, filename, db_handler):
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
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"
    endpoint = f"{endpoint}?product_id=id_1&name={filename}"
    with contextmanager(get_db)() as db:
        # Init this product into db, set the status to NOT_STARTED
        db_handler.create(
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
        result = db_handler.get(db=db, name=filename)
        # DB Status is set to failed and download started
        # Error message is written into db
        assert result.status == EDownloadStatus.FAILED
        assert data.json() == {"started": "true"}
        assert result.status_fail_message == "Exception('Some Runtime Error occured here.')"


@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize(
    "endpoint, filename, db_handler",
    [
        ("/adgs/aux", "ADGS_test_file_eodag.raw", AdgsDownloadStatus),
        ("/cadip/CADIP/cadu", "CADIP_test_file_eodag.raw", CaduDownloadStatus),
    ],
)
def test_failure_while_uploading_to_bucket(mocker, monkeypatch, client, endpoint, filename, db_handler):
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
    product_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"
    obs = "s3://some_bucket_info"
    endpoint = f"{endpoint}?product_id=id_1&name={filename}&obs={obs}"
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
        # Simulate ADGS file-stream download
        responses.add(
            responses.GET,
            "http://127.0.0.1:5001/Products(id_1)/$value",
            body="some byte-array data\n",
            status=200,
        )
        # Init this product into db, set the status to NOT_STARTED
        db_handler.create(
            db=db,
            product_id=product_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.NOT_STARTED,
        )
        # Check that product we just inserted into db is not_started
        result = db_handler.get(db=db, name=filename)
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
        result = db_handler.get(db=db, name=filename)
        # Check that update_db function set the status to FAILED
        assert result.status == EDownloadStatus.FAILED
        assert data.status_code == 200
