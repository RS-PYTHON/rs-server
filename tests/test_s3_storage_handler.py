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
import filecmp
import os
import os.path as osp
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timedelta

import pytest
import requests
from botocore.stub import Stubber
from moto.server import ThreadedMotoServer
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    SLEEP_TIME,
    GetKeysFromS3Config,
    PutFilesToS3Config,
    S3StorageHandler,
    TransferFromS3ToS3Config,
)
from rs_server_common.utils.logging import Logging

# TODO: use fixture instead ? + set environment variables in monkeypatch
from .conftest import (  # pylint: disable=no-name-in-module
    RESOURCES_FOLDER,
    export_aws_credentials,
)

FULL_FOLDER = RESOURCES_FOLDER / "s3" / "full_s3_storage_handler_test"
SHORT_FOLDER = RESOURCES_FOLDER / "s3" / "short_s3_storage_handler_test"


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint",
    [("false"), ("http://localhost:5000")],
)
def test_get_s3_client_and_disconnect(endpoint: str):
    """Test the 'get_s3_client' method of the S3StorageHandler class.

    This unit test evaluates both the 'get_s3_client' and 'disconnect' methods of the S3StorageHandler class.
    It uses the pytest.mark.parametrize decorator to run the test with different 'endpoint' values.
    The 'get_s3_client" method is expected to create an instance of the S3StorageHandler class when the
    endpoint is 'http://localhost:5000', and it should raise an exception otherwise. The 'disconnect' method should
    call the close() method of the s3 client and to set this one to None

    Args:
        endpoint (str): The endpoint to be used for testing.

    Returns:
        None

    Raises:
        AssertionError: If the test fails to create an instance of S3StorageHandler when the endpoint is valid,
        or if it fails to raise an exception when the endpoint is not valid.

    Note:
        The test requires a temporary Moto S3 server for running. It exports temporary AWS credentials,
        initializes an S3StorageHandler instance, and checks if the method behaves as expected.

    """
    server = ThreadedMotoServer()
    server.start()
    secrets = {"s3endpoint": endpoint, "accesskey": "", "secretkey": "", "region": "sbg"}
    server.stop()
    if endpoint == "http://localhost:5000":
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )
        assert s3_handler
        s3_handler.disconnect_s3()
        assert s3_handler.s3_client is None
        s3_handler.disconnect_s3()
        assert s3_handler.s3_client is None
    else:
        with pytest.raises(Exception):
            assert S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )


@pytest.mark.unit
@pytest.mark.parametrize(
    "s3cfg_file",
    [(("./USER/credentials_location/.s3cfg")), (("/path/to/none/.s3cfg"))],
)
def test_get_secrets_from_file(s3cfg_file: str):
    """Test the get_secrets_from_file method of the S3StorageHandler class."""

    secrets = {
        "s3endpoint": None,
        "accesskey": None,
        "secretkey": None,
    }

    if "USER" in s3cfg_file:
        tmp_s3cfg_file, tmp_path = tempfile.mkstemp()
        try:
            with os.fdopen(tmp_s3cfg_file, "w") as tmp:
                tmp.write("access_key = test_access_key\n")
                tmp.write("secret_key = test_secret_key\n")
                tmp.write("host_bucket = https://test_endpoint.com\n")
                tmp.write("extra_line = test_text\n")
                tmp.flush()
            S3StorageHandler.get_secrets_from_file(secrets, tmp_path)
        finally:
            os.remove(tmp_path)
    else:
        with pytest.raises(FileNotFoundError):
            S3StorageHandler.get_secrets_from_file(secrets, s3cfg_file)


@pytest.mark.unit
@pytest.mark.parametrize(
    "s3_url",
    [
        (("s3://test_bucket/test_prefix/test_file.tst")),
        (("/no/path/_to#none_file")),
    ],
)
def test_s3_path_parser(s3_url: str):
    """Test the s3_path_parser method of the S3StorageHandler class."""

    bucket, prefix, file = S3StorageHandler.s3_path_parser(s3_url)
    if "s3" in s3_url:
        assert bucket == "test_bucket"
        assert prefix == "test_prefix"
        assert file == "test_file.tst"
    else:
        assert bucket == ""
        assert prefix == "/no/path"
        assert file == "_to#none_file"


@pytest.mark.unit
def test_wait_timeout():
    """Test the wait_timeout method of the S3StorageHandler class."""

    s3_handler = S3StorageHandler(
        None,
        None,
        "http://localhost:5000",
        None,
    )
    start_p = datetime.now()
    s3_handler.wait_timeout(1)
    assert (datetime.now() - start_p) >= timedelta(seconds=1)


@pytest.mark.unit
def test_timeout(mocker):
    """Test the wait_timeout method of the S3StorageHandler class."""

    s3_handler = S3StorageHandler(
        None,
        None,
        "http://localhost:5000",
        None,
    )
    res = mocker.patch("time.sleep", side_effect=None)
    s3_handler.wait_timeout(1)
    assert res.call_count >= int(1 / SLEEP_TIME)  # 5 calls of 0.2 sec sleep = 1


@pytest.mark.unit
def test_check_file_overwriting():
    """Test the check_file_overwriting method of the S3StorageHandler class."""

    s3_handler = S3StorageHandler(
        None,
        None,
        "http://localhost:5000",
        None,
    )
    _, tmp_path = tempfile.mkstemp()
    assert not s3_handler.check_file_overwriting(tmp_path, False)
    assert os.path.isfile(tmp_path)
    assert s3_handler.check_file_overwriting(tmp_path, True)
    assert not os.path.isfile(tmp_path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "path, expected_res",
    [(("/usr/path/to/file", "file")), (("/usr/path/to/folder/", "folder"))],
)
def test_get_basename(path: str, expected_res: bool):
    """test_get_basename Function Documentation

    Test the get_basename method of the S3StorageHandler class.

    Parameters:
    - path (str): The input path to be tested.
    - expected_res (bool): The expected result of the get_basename method.

    Raises:
    - AssertionError: If the result of S3StorageHandler.get_basename(path) does not match expected_res.
    """
    assert expected_res == S3StorageHandler.get_basename(path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, bucket, nb_of_files",
    [
        (("http://localhost:5000", "test-bucket", 2012)),
        (("http://localhost:5000", "test-bucket", 999)),
        (("http://localhost:5000", "non-existent-bucket", 0)),
    ],
)
def test_list_s3_files_obj(endpoint: str, bucket: str, nb_of_files: int):
    """test_list_s3_files_obj Function Documentation

    Test the list_s3_files_obj method of the S3StorageHandler class.

    Parameters:
    - endpoint (str): The S3 endpoint for testing.
    - bucket (str): The name of the S3 bucket for testing.
    - nb_of_files (int): The expected number of files in the S3 bucket.

    Raises:
    - AssertionError: If the number of files returned by S3StorageHandler.list_s3_files_obj does not match nb_of_files.
    """
    export_aws_credentials()
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}
    logger = Logging.default(__name__)

    # create the test bucket
    server = ThreadedMotoServer()
    server.start()
    try:
        requests.post(endpoint + "/moto-api/reset", timeout=5)
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )

        with pytest.raises(Exception):
            s3_handler.check_bucket_access(bucket)
            server.stop()
            logger.error("The bucket %s does exist, for the tests it shouldn't", bucket)
            assert False
        if bucket == "test-bucket":
            s3_handler.s3_client.create_bucket(Bucket=bucket)
            for idx in range(nb_of_files):
                s3_handler.s3_client.put_object(Bucket=bucket, Key=f"test-dir/{idx}", Body="testing")
        # end of create
        try:
            s3_files = s3_handler.list_s3_files_obj(bucket, "test-dir")
        except RuntimeError:
            s3_files = []
    finally:
        server.stop()

    logger.debug("len(s3_files)  = %s", len(s3_files))
    assert len(s3_files) == nb_of_files


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, bucket",
    [(("http://localhost:5000", "test-bucket")), (("http://localhost:5000", "non-existent-bucket"))],
)
def test_check_bucket_access(endpoint: str, bucket: str):
    """test_check_bucket_access Function Documentation

    Test the check_bucket_access method of the S3StorageHandler class.

    Parameters:
    - endpoint (str): The S3 endpoint for testing.
    - bucket (str): The name of the S3 bucket for testing.

    Raises:
    - AssertionError: If the result of S3StorageHandler.check_bucket_access does not match the expected result.
    """
    export_aws_credentials()
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}

    server = ThreadedMotoServer()
    server.start()
    try:
        requests.post(endpoint + "/moto-api/reset", timeout=5)
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )

        if bucket == "test-bucket":
            # create the test-bucket storage only when needed
            s3_handler.s3_client.create_bucket(Bucket=bucket)
            s3_handler.check_bucket_access(bucket)
        else:
            with pytest.raises(Exception):
                s3_handler.check_bucket_access(bucket)
    finally:
        server.stop()


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, bucket, lst_with_files, expected_res",
    [
        (
            (
                "http://localhost:5000",
                "test-bucket",
                [
                    "s3_storage_handler_test/no_root_file1",
                    "s3_storage_handler_test/no_root_file2",
                    "s3_storage_handler_test/subdir_1",
                    "s3_storage_handler_test/subdir_2",
                ],
                [
                    ("", "s3_storage_handler_test/no_root_file1"),
                    ("", "s3_storage_handler_test/no_root_file2"),
                    ("subdir_1", "s3_storage_handler_test/subdir_1/subdir_file"),
                    ("subdir_1/subsubdir_1", "s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file1"),
                    ("subdir_1/subsubdir_1", "s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file2"),
                    ("subdir_1/subsubdir_2", "s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file1"),
                    ("subdir_1/subsubdir_2", "s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file2"),
                    ("subdir_2", "s3_storage_handler_test/subdir_2/subdir_2_file1"),
                    ("subdir_2", "s3_storage_handler_test/subdir_2/subdir_2_file2"),
                ],
            )
        ),
        (
            (
                "http://localhost:5000",
                "test-bucket",
                ["nonexistent_1", "nonexistent_2/file1", "s3_storage_handler_test/no_root_file1"],
                [
                    (None, "nonexistent_1"),
                    (None, "nonexistent_2/file1"),
                    ("", "s3_storage_handler_test/no_root_file1"),
                ],
            )
        ),
        (
            (
                "http://localhost:5000",
                "nonexistent_bucket",
                ["nonexistent_1", "nonexistent_2/file1", "s3_storage_handler_test/no_root_file1"],
                [],
            )
        ),
    ],
)
def test_files_to_be_downloaded(
    endpoint: str,
    bucket: str,
    lst_with_files: list,
    expected_res: list,
):
    """test_files_to_be_downloaded Function Documentation

    Test the files_to_be_downloaded method of the S3StorageHandler class.

    Parameters:
    - endpoint (str): The S3 endpoint for testing.
    - bucket (str): The name of the S3 bucket for testing.
    - lst_with_files (list): List of files to be checked for download.
    - expected_res (list): List of tuples representing the expected files to be
     downloaded. Each tuple consists of a prefix and a file path.

    Raises:
    - AssertionError: If the result of S3StorageHandler.files_to_be_downloaded does not match expected_res.
    """

    export_aws_credentials()
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}
    logger = Logging.default(__name__)

    server = ThreadedMotoServer()
    server.start()
    try:
        requests.post(endpoint + "/moto-api/reset", timeout=5)
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )

        if bucket == "test-bucket":
            s3_handler.s3_client.create_bucket(Bucket=bucket)
            for obj in expected_res:
                if obj[0] is not None:
                    s3_handler.s3_client.put_object(Bucket=bucket, Key=obj[1], Body="testing")
        logger.debug("Bucket created !")
        try:
            collection = s3_handler.files_to_be_downloaded(bucket, lst_with_files)
        except RuntimeError:
            collection = []
    finally:
        server.stop()

    assert len(Counter(collection) - Counter(expected_res)) == 0
    assert len(Counter(expected_res) - Counter(collection)) == 0


def cmp_dirs(dir1, dir2):
    """cmp_dirs Function Documentation

    Compare two directories recursively. Files in each directory are
    assumed to be equal if their names and contents are equal.

    @param dir1: First directory path
    @param dir2: Second directory path

    @return: True if the directory trees are the same and
        there were no errors while accessing the directories or files,
        False otherwise.
    """
    dirs_cmp = filecmp.dircmp(dir1, dir2)
    if len(dirs_cmp.left_only) > 0 or len(dirs_cmp.right_only) > 0 or len(dirs_cmp.funny_files) > 0:
        return False
    (_, mismatch, errors) = filecmp.cmpfiles(dir1, dir2, dirs_cmp.common_files, shallow=False)
    if len(mismatch) > 0 or len(errors) > 0:
        return False
    for common_dir in dirs_cmp.common_dirs:
        new_dir1 = osp.join(dir1, common_dir)
        new_dir2 = osp.join(dir2, common_dir)
        if not cmp_dirs(new_dir1, new_dir2):
            return False
    return True


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, bucket, lst_with_files, lst_with_files_to_be_dwn, expected_res",
    [
        (
            (
                "http://localhost:5000",
                "test-bucket",
                [
                    "s3_storage_handler_test/no_root_file1",
                    "s3_storage_handler_test/no_root_file2",
                    "s3_storage_handler_test/subdir_1",
                    "s3_storage_handler_test/subdir_2",
                ],
                [
                    ("", "s3_storage_handler_test/no_root_file1"),
                    ("", "s3_storage_handler_test/no_root_file2"),
                    ("subdir_1", "s3_storage_handler_test/subdir_1/subdir_file"),
                    ("subdir_1/subsubdir_1", "s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file1"),
                    ("subdir_1/subsubdir_1", "s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file2"),
                    ("subdir_1/subsubdir_2", "s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file1"),
                    ("subdir_1/subsubdir_2", "s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file2"),
                    ("subdir_2", "s3_storage_handler_test/subdir_2/subdir_2_file1"),
                    ("subdir_2", "s3_storage_handler_test/subdir_2/subdir_2_file2"),
                ],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "test-bucket",
                ["nonexistent_1", "nonexistent_2/file1", "s3_storage_handler_test/no_root_file1"],
                [("", "s3_storage_handler_test/no_root_file1")],
                ["nonexistent_1", "nonexistent_2/file1"],
            )
        ),
        (
            (
                "http://localhost:5000",
                "non-existent-bucket",
                ["nonexistent_1", "nonexistent_2/file1", "s3_storage_handler_test/no_root_file1"],
                [],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "test-bucket",
                [
                    "s3_storage_handler_test/no_root_file1",
                    "s3_storage_handler_test/no_root_file2",
                    "s3_storage_handler_test/subdir_1",
                    "s3_storage_handler_test/subdir_2",
                    "s3_storage_handler_test/fake1",
                    "s3_storage_handler_test/fake2",
                    "s3_storage_handler_test/subdir_2",
                ],
                [
                    ("", "s3_storage_handler_test/no_root_file1"),
                    ("", "s3_storage_handler_test/no_root_file2"),
                    ("subdir_1", "s3_storage_handler_test/subdir_1/subdir_file"),
                    ("subdir_1/subsubdir_1", "s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file1"),
                    ("subdir_1/subsubdir_1", "s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file2"),
                    ("subdir_1/subsubdir_2", "s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file1"),
                    ("subdir_1/subsubdir_2", "s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file2"),
                    ("subdir_2", "s3_storage_handler_test/subdir_2/subdir_2_file1"),
                    ("subdir_2", "s3_storage_handler_test/subdir_2/subdir_2_file2"),
                ],
                ["s3_storage_handler_test/fake1", "s3_storage_handler_test/fake2"],
            )
        ),
    ],
)
def test_get_keys_from_s3(
    endpoint: str,
    bucket: str,
    lst_with_files: list,
    lst_with_files_to_be_dwn: list,
    expected_res: list,
):
    """test_get_keys_from_s3 Function Documentation

    Test the get_keys_from_s3 function.

    Parameters:
    - endpoint (str): The S3 endpoint for testing.
    - bucket (str): The name of the S3 bucket for testing.
    - lst_with_files (list): List of files to be checked for download.
    - lst_with_files_to_be_dwn (list): List of tuples representing the expected
    files to be downloaded. Each tuple consists of a prefix and a file path.
    - expected_res (list): List of tuples representing the expected result of the Prefect workflow.

    Raises:
    - AssertionError: If the result of the Prefect workflow does not match expected_res.
    """
    export_aws_credentials()
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}

    short_s3_storage_handler_test_nb_of_files = 3
    logger = Logging.default(__name__)

    # create the test bucket
    server = ThreadedMotoServer()
    server.start()
    try:
        requests.post(endpoint + "/moto-api/reset", timeout=5)
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )

        if bucket == "test-bucket":
            s3_handler.s3_client.create_bucket(Bucket=bucket)
            for obj in lst_with_files_to_be_dwn:
                s3_handler.s3_client.put_object(Bucket=bucket, Key=obj[1], Body="testing\n")
        # end of create

        local_path = tempfile.mkdtemp()

        config = GetKeysFromS3Config(
            lst_with_files,
            bucket,
            local_path,
            False,
            1,
        )

        res = s3_handler.get_keys_from_s3(config)
        logger.debug("get_keys_from_s3 returns: %s", res)
    except RuntimeError:
        assert bucket == "non-existent-bucket"
        res = []
    finally:
        server.stop()

    assert len(Counter(expected_res) - Counter(res)) == 0
    assert len(Counter(res) - Counter(expected_res)) == 0

    if bucket == "test-bucket":
        try:
            if len(lst_with_files) > short_s3_storage_handler_test_nb_of_files:
                assert cmp_dirs(FULL_FOLDER, local_path)
            else:
                assert cmp_dirs(SHORT_FOLDER, local_path)
            shutil.rmtree(local_path)
        except OSError:
            logger.error("The local path was not created")
            assert False


@pytest.mark.unit
@pytest.mark.parametrize(
    "lst_with_files, expected_res",
    [
        (
            (
                [
                    f"{FULL_FOLDER}/no_root_file1",
                    f"{FULL_FOLDER}/no_root_file2",
                    f"{FULL_FOLDER}/subdir_1",
                    f"{FULL_FOLDER}/subdir_2",
                ],
                [
                    ("", f"{FULL_FOLDER}/no_root_file1"),
                    ("", f"{FULL_FOLDER}/no_root_file2"),
                    ("subdir_1", f"{FULL_FOLDER}/subdir_1/subdir_file"),
                    (
                        "subdir_1/subsubdir_1",
                        f"{FULL_FOLDER}/subdir_1/subsubdir_1/subsubdir_file1",
                    ),
                    (
                        "subdir_1/subsubdir_1",
                        f"{FULL_FOLDER}/subdir_1/subsubdir_1/subsubdir_file2",
                    ),
                    (
                        "subdir_1/subsubdir_2",
                        f"{FULL_FOLDER}/subdir_1/subsubdir_2/subsubdir_2_file1",
                    ),
                    (
                        "subdir_1/subsubdir_2",
                        f"{FULL_FOLDER}/subdir_1/subsubdir_2/subsubdir_2_file2",
                    ),
                    ("subdir_2", f"{FULL_FOLDER}/subdir_2/subdir_2_file1"),
                    ("subdir_2", f"{FULL_FOLDER}/subdir_2/subdir_2_file2"),
                ],
            )
        ),
        (
            (
                [
                    "nonexistent_1",
                    "nonexistent_2/file1",
                    f"{FULL_FOLDER}/no_root_file1",
                ],
                [
                    ("", f"{FULL_FOLDER}/no_root_file1"),
                ],
            )
        ),
    ],
)
def test_files_to_be_uploaded(lst_with_files: list, expected_res: list):
    """Test the 'files_to_be_uploaded' method of the S3StorageHandler class.

    This unit test function evaluates the 'files_to_be_uploaded' method of the S3StorageHandler class.
    It sets up a temporary Moto S3 server, initializes an S3StorageHandler instance, and compares the
    result of the method with the expected result.

    Args:
        lst_with_files (list): The list of local files to be uploaded.
        expected_res (list): The expected result of the 'files_to_be_uploaded' method.

    Returns:
        None

    Raises:
        AssertionError: If the actual result differs from the expected result.

    Note:
        The test requires a temporary Moto S3 server for running. It exports temporary AWS credentials,
        initializes an S3StorageHandler instance, and checks if the method produces the expected result.

    """
    export_aws_credentials()
    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    logger = Logging.default(__name__)

    server = ThreadedMotoServer()
    server.start()
    try:
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )
    finally:
        server.stop()

    collection = s3_handler.files_to_be_uploaded(lst_with_files)
    logger.debug("collection   = %s", collection)
    logger.debug("expected_res = %s", expected_res)
    assert len(Counter(collection) - Counter(expected_res)) == 0
    assert len(Counter(expected_res) - Counter(collection)) == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, bucket, s3_prefix, lst_with_files, keys_in_bucket, expected_res",
    [
        (
            (
                "http://localhost:5000",
                "test-bucket",
                f"{FULL_FOLDER}",
                [
                    f"{FULL_FOLDER}/no_root_file1",
                    f"{FULL_FOLDER}/no_root_file2",
                    f"{FULL_FOLDER}/subdir_1",
                    f"{FULL_FOLDER}/subdir_2",
                ],
                [
                    f"{FULL_FOLDER}/no_root_file1",
                    f"{FULL_FOLDER}/no_root_file2",
                    f"{FULL_FOLDER}/subdir_1/subdir_file",
                    f"{FULL_FOLDER}/subdir_1/subsubdir_1/subsubdir_file1",
                    f"{FULL_FOLDER}/subdir_1/subsubdir_1/subsubdir_file2",
                    f"{FULL_FOLDER}/subdir_1/subsubdir_2/subsubdir_2_file1",
                    f"{FULL_FOLDER}/subdir_1/subsubdir_2/subsubdir_2_file2",
                    f"{FULL_FOLDER}/subdir_2/subdir_2_file1",
                    f"{FULL_FOLDER}/subdir_2/subdir_2_file2",
                ],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "test-bucket",
                f"{SHORT_FOLDER}",
                [
                    "nonexistent_1",
                    "nonexistent_2/file1",
                    f"{SHORT_FOLDER}/no_root_file1",
                ],
                [f"{SHORT_FOLDER}/no_root_file1"],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "non-existent-bucket",
                "non_existent_dir",
                [
                    "nonexistent_1",
                    "nonexistent_2/file1",
                    f"{SHORT_FOLDER}/no_root_file1",
                ],
                [],
                [f"{SHORT_FOLDER}/no_root_file1"],
            )
        ),
    ],
)
def test_put_files_to_s3(
    endpoint: str,
    bucket: str,
    s3_prefix: str,
    lst_with_files: list,
    keys_in_bucket: list,
    expected_res: list,
):
    """Test the 'put_files_to_s3' method of the S3StorageHandler class.

    This test function evaluates the 'put_files_to_s3' method of the S3StorageHandler class. It sets up a temporary
    Moto S3 server, initializes an S3StorageHandler instance, and checks if the method produces the expected result.

    Args:
        endpoint (str): The endpoint for the temporary Moto S3 server.
        bucket (str): The name of the S3 bucket to be used for testing.
        s3_prefix (str): The S3 prefix for the test files.
        lst_with_files (list): List of local files to be checked for upload.
        keys_in_bucket (list): List of keys expected to be present in the S3 bucket.
        expected_res (list): List of tuples representing the expected files to be uploaded.
            Each tuple consists of a prefix and a file path.

    Returns:
        None

    Raises:
        AssertionError: If the result of S3StorageHandler.files_to_be_uploaded does not match expected_res.

    Note:
        The test requires a temporary Moto S3 server for running. It exports temporary AWS credentials,
        initializes an S3StorageHandler instance, and checks if the method produces the expected result.

    """

    export_aws_credentials()
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}

    # create the test bucket
    server = ThreadedMotoServer()
    server.start()
    try:
        requests.post(endpoint + "/moto-api/reset", timeout=5)
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )
        if bucket == "test-bucket":
            s3_handler.s3_client.create_bucket(Bucket=bucket)
        # end of create

        test_bucket_files = []  # type: list[str]
        config = PutFilesToS3Config(lst_with_files, bucket, s3_prefix, 1)
        res = s3_handler.put_files_to_s3(config)

        for key in lst_with_files:
            test_bucket_files = test_bucket_files + s3_handler.list_s3_files_obj(bucket, key)
        print(f"test_bucket_files = {test_bucket_files}")

    except RuntimeError:
        assert bucket == "non-existent-bucket"
    finally:
        server.stop()

    if bucket != "non-existent-bucket":
        assert len(Counter(keys_in_bucket) - Counter(test_bucket_files)) == 0
        assert len(Counter(test_bucket_files) - Counter(keys_in_bucket)) == 0
        assert len(Counter(expected_res) - Counter(res)) == 0
        assert len(Counter(res) - Counter(expected_res)) == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, bucket_src, lst_with_files, bucket_dst, lst_with_files_to_be_copied, expected_res",
    [
        (
            (
                "http://localhost:5000",
                "source-bucket",
                [
                    "s3_storage_handler_test/no_root_file1",
                    "s3_storage_handler_test/no_root_file2",
                    "s3_storage_handler_test/subdir_1",
                    "s3_storage_handler_test/subdir_2",
                ],
                "destination-bucket",
                [
                    "s3_storage_handler_test/no_root_file1",
                    "s3_storage_handler_test/no_root_file2",
                    "s3_storage_handler_test/subdir_1/subdir_file",
                    "s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file1",
                    "s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file2",
                    "s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file1",
                    "s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file2",
                    "s3_storage_handler_test/subdir_2/subdir_2_file1",
                    "s3_storage_handler_test/subdir_2/subdir_2_file2",
                ],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "source-bucket",
                ["nonexistent_1", "nonexistent_2/file1", "s3_storage_handler_test/no_root_file1"],
                "destination-bucket",
                ["s3_storage_handler_test/no_root_file1"],
                [
                    "nonexistent_1",
                    "nonexistent_2/file1",
                ],
            )
        ),
        (
            (
                "http://localhost:5000",
                "non-existent-bucket",
                ["nonexistent_1", "nonexistent_2/file1", "s3_storage_handler_test/no_root_file1"],
                "destination-bucket",
                [],
                [],
            )
        ),
    ],
)
def test_transfer_from_s3_to_s3(
    endpoint: str,
    bucket_src: str,
    lst_with_files: list,
    bucket_dst: str,
    lst_with_files_to_be_copied: list,
    expected_res: list,
):
    """test_transfer_from_s3_to_s3 Function Documentation

    Test the transfer_from_s3_to_s3  method of the S3StorageHandler class.

    Parameters:
    - endpoint (str): The S3 endpoint for testing.
    - bucket (str): The name of the S3 bucket for testing.
    - lst_with_files (list): List of files to be checked for download.
    - lst_with_files_to_be_dwn (list): List of tuples representing the expected
    files to be downloaded. Each tuple consists of a prefix and a file path.
    - expected_res (list): List of tuples representing the expected result of the Prefect workflow.

    Raises:
    - AssertionError: If the result of the Prefect workflow does not match expected_res.
    """

    export_aws_credentials()
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}

    # create the test bucket
    try:
        server = ThreadedMotoServer()
        server.start()
        requests.post(endpoint + "/moto-api/reset", timeout=5)
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )
        if bucket_src == "source-bucket":
            s3_handler.s3_client.create_bucket(Bucket=bucket_src)
            for obj in lst_with_files_to_be_copied:
                if "nonexistent" not in obj:
                    s3_handler.s3_client.put_object(Bucket=bucket_src, Key=obj, Body="testing\n")
        if bucket_dst == "destination-bucket":
            s3_handler.s3_client.create_bucket(Bucket=bucket_dst)
        # end of create

        config = TransferFromS3ToS3Config(
            lst_with_files,
            bucket_src,
            bucket_dst,
            max_retries=1,
        )

        res = s3_handler.transfer_from_s3_to_s3(config)
        assert res == expected_res
        if bucket_dst == "destination-bucket":
            assert lst_with_files_to_be_copied == s3_handler.list_s3_files_obj(bucket_dst, "")

    except RuntimeError:
        assert bucket_src == "non-existent-bucket"
    finally:
        server.stop()


@pytest.mark.unit
def test_delete_file_from_s3():
    """Test handling of s3 client exceptions while deleting a file from a bucket"""

    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    s3_handler = S3StorageHandler(
        secrets["accesskey"],
        secrets["secretkey"],
        secrets["s3endpoint"],
        secrets["region"],
    )

    with pytest.raises(RuntimeError) as exc:
        s3_handler.delete_file_from_s3("some_s3_2", None)
    assert str(exc.value) == "Input error for deleting the file"

    boto_mocker = Stubber(s3_handler.s3_client)
    boto_mocker.add_client_error("delete_object", 500)
    with pytest.raises(RuntimeError) as exc:
        s3_handler.delete_file_from_s3("some_s3_1", "some_file_1")
    assert str(exc.value) == "Failed to delete key s3://some_s3_1/some_file_1"
