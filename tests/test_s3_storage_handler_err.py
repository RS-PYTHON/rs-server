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


import pytest
import requests
from botocore.stub import Stubber
from moto.server import ThreadedMotoServer
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    DWN_S3FILE_RETRY_TIMEOUT,
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
