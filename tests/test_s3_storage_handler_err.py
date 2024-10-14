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

"""Docstring to be added."""

# pylint: disable=R0913,R0914 # Too many arguments, Too many local variables


import botocore
import pytest
import requests
import responses
from botocore.stub import Stubber
from moto.server import ThreadedMotoServer
from requests.auth import HTTPBasicAuth
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    DWN_S3FILE_RETRY_TIMEOUT,
    S3_MAX_RETRIES,
    SLEEP_TIME,
    GetKeysFromS3Config,
    PutFilesToS3Config,
    S3StorageHandler,
    TransferFromS3ToS3Config,
)

# TODO: use fixture instead ? + set environment variables in monkeypatch
from .conftest import (  # pylint: disable=no-name-in-module
    RESOURCES_FOLDER,
    export_aws_credentials,
)

SHORT_FOLDER = RESOURCES_FOLDER / "s3" / "short_s3_storage_handler_test"


@pytest.mark.unit
def test_client_exception_while_checking_access_handling():
    """Test handling of client exceptions while checking access."""

    export_aws_credentials()
    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    s3_handler = S3StorageHandler(
        secrets["accesskey"],
        secrets["secretkey"],
        secrets["s3endpoint"],
        secrets["region"],
    )
    boto_mocker = Stubber(s3_handler.s3_client)

    boto_mocker.add_client_error("head_bucket", 403)
    boto_mocker.activate()
    with pytest.raises(RuntimeError) as exc:
        s3_handler.check_bucket_access("some_s3_1")
    assert str(exc.value) == "some_s3_1 is a private bucket. Forbidden access!"

    boto_mocker.add_client_error("head_bucket", 404)
    with pytest.raises(RuntimeError) as exc:
        s3_handler.check_bucket_access("some_s3_2")
    assert str(exc.value) == "some_s3_2 bucket does not exist!"
    assert str(exc.value) != "Exception when checking the access to some_s3_1 bucket!"

    boto_mocker.add_client_error("head_bucket", 500)
    with pytest.raises(RuntimeError) as exc:
        s3_handler.check_bucket_access("some_s3_3")
    assert str(exc.value) == "Exception when checking the access to some_s3_3 bucket"
    boto_mocker.deactivate()


@pytest.mark.unit
def test_get_keys_from_s3_download_fail(mocker):
    """test_get_keys_from_s3_download_fail Function Documentation

    Test the get_keys_from_s3  method of the S3StorageHandler class in case of a download failure.
    """

    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    # create the test bucket
    # Test with a running s3 server
    server = ThreadedMotoServer()
    server.start()
    requests.post("http://localhost:5000/moto-api/reset", timeout=5)
    s3_handler = S3StorageHandler(
        secrets["accesskey"],
        secrets["secretkey"],
        secrets["s3endpoint"],
        secrets["region"],
    )

    config = GetKeysFromS3Config(
        ["fake"],
        "test-bucket",
        "local_path",
        False,
        1,
    )
    mocker.patch(
        "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.check_bucket_access",
        return_value=None,
    )
    mocker.patch(
        "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.files_to_be_downloaded",
        return_value=[("", "path1"), ("", "path2")],
    )
    res = mocker.patch("time.sleep", side_effect=None)
    # The internal exception should be: "Exception: An error occurred (404) when calling
    # the HeadObject operation: Not Found:
    # and the error: "Could not download the file path1. The download was retried for 1 times. Aborting"
    # Same thing for the path2
    ret = s3_handler.get_keys_from_s3(config)
    assert ret == ["path1", "path2"]
    # nb of calls to time.sleep for retrying the download  of 2 files
    assert res.call_count >= int(DWN_S3FILE_RETRY_TIMEOUT / SLEEP_TIME)
    server.stop()

    # Stop the server and re-test the function again
    # this time, the exception should be "botocore.exceptions.EndpointConnectionError:
    # Could not connect to the endpoint URL: "http://localhost:5000/"
    # and the error: Could not download the file path1. The download was retried for 1 times. Aborting
    # Same thing for the path2
    ret = s3_handler.get_keys_from_s3(config)
    assert ret == ["path1", "path2"]

    # mock the connect_s3
    mocker.patch(
        "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.connect_s3",
        return_value=None,
        side_effect=RuntimeError,
    )
    # call get_keys_from_s3, this time the exception should be a RuntimeError
    ret = s3_handler.get_keys_from_s3(config)
    assert ret == ["path1", "path2"]


@pytest.mark.unit
def test_put_files_to_s3_upload_fail(mocker):
    """test_put_files_to_s3_upload_fail Function Documentation

    Test the get_keys_from_s3  method of the S3StorageHandler class in case of an upload failure.
    """

    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    # create the test bucket
    # Test with a running s3 server
    server = ThreadedMotoServer()
    server.start()
    requests.post("http://localhost:5000/moto-api/reset", timeout=5)
    s3_handler = S3StorageHandler(
        secrets["accesskey"],
        secrets["secretkey"],
        secrets["s3endpoint"],
        secrets["region"],
    )

    config = PutFilesToS3Config(
        [SHORT_FOLDER],
        "test-bucket",
        "s3_path",
        1,
    )
    mocker.patch(
        "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.check_bucket_access",
        return_value=None,
    )
    mocker.patch(
        "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.files_to_be_uploaded",
        return_value=[(f"{SHORT_FOLDER}", f"{SHORT_FOLDER}/no_root_file1")],
    )
    res = mocker.patch("time.sleep", side_effect=None)
    s3_handler.s3_client.create_bucket(Bucket="test-bucket")
    boto_mocker = Stubber(s3_handler.s3_client)

    boto_mocker.add_client_error("put_object", service_error_code="RuntimeError")
    boto_mocker.activate()

    ret = s3_handler.put_files_to_s3(config)
    # nb of calls to time.sleep for retrying the upload of 1 file
    assert res.call_count >= int(DWN_S3FILE_RETRY_TIMEOUT / SLEEP_TIME)
    assert ret == [f"{SHORT_FOLDER}/no_root_file1"]
    server.stop()


@pytest.mark.unit
def test_transfer_from_s3_to_s3_fail(mocker):
    """test_transfer_from_s3_to_s3_fail Function Documentation

    Test the transfer_from_s3_to_s3 method of the S3StorageHandler class in case of a file transfer failure.
    """
    bucket_src = "bucket_src"
    bucket_dst = "bucket_dst"
    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    # create the test bucket
    # Test with a running s3 server
    server = ThreadedMotoServer()
    server.start()
    requests.post("http://localhost:5000/moto-api/reset", timeout=5)
    s3_handler = S3StorageHandler(
        secrets["accesskey"],
        secrets["secretkey"],
        secrets["s3endpoint"],
        secrets["region"],
    )
    s3_handler.s3_client.create_bucket(Bucket=bucket_src)
    s3_handler.s3_client.create_bucket(Bucket=bucket_src)
    lst_files = ["s3_storage_handler_test/no_root_file1"]
    for obj in lst_files:
        s3_handler.s3_client.put_object(Bucket=bucket_src, Key=obj, Body="testing\n")
    config = TransferFromS3ToS3Config(
        lst_files,
        bucket_src,
        bucket_dst,
        max_retries=1,
    )
    mocker.patch(
        "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.check_bucket_access",
        return_value=None,
    )
    mocker.patch(
        "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.files_to_be_downloaded",
        return_value=[("", lst_files[0])],
    )
    res = mocker.patch("time.sleep", side_effect=None)
    boto_mocker = Stubber(s3_handler.s3_client)

    boto_mocker.add_client_error("copy_object", service_error_code="RuntimeError")
    boto_mocker.activate()
    # The internal exception should be: "Exception: An error occurred (404) when calling
    # the HeadObject operation: Not Found:
    # and the error: "Could not download the file path1. The download was retried for 1 times. Aborting"
    # Same thing for the path2
    ret = s3_handler.transfer_from_s3_to_s3(config)
    assert ret == ["s3_storage_handler_test/no_root_file1"]
    # nb of calls to time.sleep for retrying the download  of 1 file
    assert res.call_count == int(DWN_S3FILE_RETRY_TIMEOUT / SLEEP_TIME)
    server.stop()
    boto_mocker.deactivate()


@pytest.mark.unit
def test_delete_file_from_s3_fail():
    """Test handling of s3 client exceptions while deleting a file from a bucket

    Test error handling when attempting to delete a file from an S3 bucket with invalid
    inputs and simulated S3 client failures.

    This unit test verifies the behavior of the `delete_file_from_s3` method in the `S3StorageHandler` class when:
        1. An invalid input (e.g., `None` for the file name) is provided.
        2. The S3 client raises an exception during the deletion process.

    The test ensures that the method raises the expected `RuntimeError` in both cases.

    Test flow:
        1. Start a mock S3 server using `ThreadedMotoServer`.
        2. Attempt to delete a file from a non-existent bucket with an invalid file name (`None`).
        3. Simulate an S3 client failure during the file deletion process and ensure the proper exception is raised.

    Raises:
        AssertionError: If the `RuntimeError` is not raised as expected or if the exception message does not
        match the expected value.
    """
    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    # create the test bucket
    # Test with a running s3 server
    server = ThreadedMotoServer()
    server.start()
    requests.post("http://localhost:5000/moto-api/reset", timeout=5)
    s3_handler = S3StorageHandler(
        secrets["accesskey"],
        secrets["secretkey"],
        secrets["s3endpoint"],
        secrets["region"],
    )
    # test when there is no file to be deleted
    with pytest.raises(RuntimeError) as exc:
        s3_handler.delete_file_from_s3("some_s3_2", None)
    assert str(exc.value) == "Input error for deleting the file"
    # prepare a bucket for tests
    bucket = "some_s3"
    s3_handler.s3_client.create_bucket(Bucket=bucket)

    # test when an exception occurs for the delete_object s3 function
    boto_mocker = Stubber(s3_handler.s3_client)
    boto_mocker.add_client_error("delete_object", service_error_code="botocore.exceptions.BotoCoreError")
    boto_mocker.activate()

    with pytest.raises(RuntimeError) as exc:
        s3_handler.delete_file_from_s3(bucket, "some_file_1", 1)

    assert str(exc.value) == f"Failed to delete key s3://{bucket}/some_file_1"
    boto_mocker.deactivate()

    server.stop()


@pytest.mark.unit
@responses.activate
def test_s3_streaming_upload_fail(mocker):
    """Unit test to validate error handling in the `s3_streaming_upload` method when streaming a file from
    an HTTP URL to an S3 bucket fails under various conditions.

    This test ensures that the `s3_streaming_upload` method in the `S3StorageHandler` class handles
    input validation errors, HTTP request failures, and S3 client errors correctly by raising a
    `RuntimeError` with appropriate messages.

    Steps:
    1. **S3 Server Setup**:
        - A `ThreadedMotoServer` is used to simulate an S3-compatible server for testing purposes.
        - The test creates a bucket (`s3-bucket-streaming`) in this mock S3 server.

    2. **Input Validation Errors**:
        - It tests that the method raises `RuntimeError` when invalid inputs (such as a `None` bucket
          or key) are provided, ensuring proper input validation.

    3. **HTTP Request Failures**:
        - The test patches `requests.get` to simulate different HTTP errors (`HTTPError`, `Timeout`,
          `RequestException`, and `ConnectionError`) and checks that the method correctly handles
          each error, retries up to `S3_MAX_RETRIES`, and raises a `RuntimeError` if retries are exhausted.

    4. **S3 Client Failures**:
        - The test simulates S3 client errors (`BotoCoreError`, `ClientError`) during the `upload_fileobj`
          call by using `Stubber`. It verifies that the retry mechanism is triggered and a `RuntimeError`
          is raised after the maximum retry attempts.

    5. **Patch & Assertion**:
        - The `wait_timeout` method in `S3StorageHandler` is patched to speed up the retries for testing.
        - It asserts that the appropriate error messages are included in the raised exceptions and that
          the retry logic behaves as expected.

    Args:
        mocker: Pytest mocker fixture used for patching and stubbing functions during tests.

    Raises:
        RuntimeError: Raised in the following cases:
            - Invalid input parameters (e.g., missing bucket or key).
            - HTTP request failures (e.g., timeout, connection errors).
            - S3 client failures (e.g., failed uploads due to S3-related exceptions).

        AssertionError: If any part of the test fails.
    """
    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    stream_url = "http://127.0.0.1:6000/file"
    auth = HTTPBasicAuth("user", "pass")

    # Test with a running s3 server
    server = ThreadedMotoServer()
    server.start()

    s3_handler = S3StorageHandler(
        secrets["accesskey"],
        secrets["secretkey"],
        secrets["s3endpoint"],
        secrets["region"],
    )
    # prepare a bucket for tests
    bucket = "s3-bucket-streaming"
    s3_handler.s3_client.create_bucket(Bucket=bucket)
    s3_key = "test_key.tst"

    # test when there is no file to be deleted
    with pytest.raises(RuntimeError) as exc:
        s3_handler.s3_streaming_upload(stream_url, auth, None, s3_key)
    assert "Input error for streaming the file from" in str(exc.value)
    # test when there is no file to be deleted
    with pytest.raises(RuntimeError) as exc:
        s3_handler.s3_streaming_upload(stream_url, auth, bucket, None)
    assert "Input error for streaming the file from" in str(exc.value)
    # mock the rs_server_common.s3_storage_handler.wait_timeout function to speed up the test
    res = mocker.patch(
        "rs_server_common.s3_storage_handler.s3_storage_handler.S3StorageHandler.wait_timeout",
        side_effect=None,
    )
    # test when an exception occurs for requests.get function
    # Loop trough all possible exception raised during request.get and check if failure happen
    for possible_exception in [
        requests.exceptions.HTTPError,
        requests.exceptions.Timeout,
        requests.exceptions.RequestException,
        requests.exceptions.ConnectionError,
    ]:
        mocker.patch("requests.get", side_effect=possible_exception("HTTP Error"))
        with pytest.raises(RuntimeError) as exc:
            s3_handler.s3_streaming_upload(stream_url, auth, bucket, s3_key)

        assert "Failed to stream the file from" in str(exc.value)
        assert res.call_count == S3_MAX_RETRIES - 1
        res.call_count = 0
    body = "some byte-array data to test the streaming of a file from http to a s3 bucket\n"
    # Add a server response for downloading one file
    responses.add(
        responses.GET,
        stream_url,
        body=body,
        status=200,
    )
    # test when an exception occurs for the upload_fileobj s3 function
    for possible_exception in [
        botocore.exceptions.BotoCoreError,
        botocore.client.ClientError,
    ]:
        boto_mocker = Stubber(s3_handler.s3_client)
        boto_mocker.add_client_error("upload_fileobj", service_error_code=possible_exception)
        boto_mocker.activate()

        with pytest.raises(RuntimeError) as exc:
            s3_handler.s3_streaming_upload(stream_url, auth, bucket, s3_key)

        assert "Failed to stream the file from" in str(exc.value)
        assert res.call_count == S3_MAX_RETRIES - 1
        res.call_count = 0
        boto_mocker.deactivate()

    server.stop()
