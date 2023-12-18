"""Docstring to be added."""
import filecmp
import logging
import os
import shutil
import sys
from collections import Counter

import pytest
import requests
from moto.server import ThreadedMotoServer
from prefect import flow

from rs_server.s3_storage_handler.s3_storage_handler import (
    S3StorageHandler,
    PrefectGetKeysFromS3Config,
    PrefectPutFilesToS3Config,
    prefect_get_keys_from_s3,
    prefect_put_files_to_s3,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint",
    [("false"), ("http://localhost:5000")],
)
def test_get_s3_client(endpoint: str):
    """test_get_s3_client Function Documentation

    This module provides unit tests for the `S3StorageHandler` class, focusing on the
    `test_get_s3_client` function.

    Usage:
        - To execute the unit tests, run the associated test module.
        - The tests cover the initialization of the `S3StorageHandler` class with different
          S3 endpoints.

    Dependencies:
        - pytest
        - ThreadedMotoServer (from your implementation or external source)
        - S3StorageHandler (class to be tested)

    Test Parameters:
        - Two sets of parameters are used for testing, each representing a test case:
            - ("false", False): Testing with a false endpoint.
            - ("http://localhost:5000", True): Testing with a valid endpoint.

    Test Execution:
        - For each test case, a threaded Moto server is started to simulate an S3 server environment.
        - A logger is set up to capture logs during the test execution.
        - The `S3StorageHandler` is instantiated with the provided parameters.
        - Assertions are made based on the expected result for each test case.
            - If the endpoint is "http://localhost:5000", the instantiation should not raise an exception.
            - If the endpoint is "false" or any other value, an exception is expected.

    Function Signature:
        def test_get_s3_client(endpoint: str, expected_res: bool)

    Parameters:
        - endpoint (str): S3 endpoint to be tested.
        - expected_res (bool): Expected result of the test case.

    Raises:
        - AssertionError: If the test case fails.

    Note:
        - Ensure that the necessary dependencies (pytest, ThreadedMotoServer, S3StorageHandler) are installed.
        - The Moto server and logger setup are common to both test cases.
    """
    server = ThreadedMotoServer()
    server.start()
    secrets = {"s3endpoint": endpoint, "accesskey": "", "secretkey": "", "region": "sbg"}

    logger = logging.getLogger("s3_storage_handler_test")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.addHandler(logging.StreamHandler(sys.stdout))

    server.stop()
    if endpoint == "http://localhost:5000":
        assert S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], secrets["region"])
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
    "s3cfg_file, expected_res",
    [(("/home/USER/.s3cfg", True)), (("/path/to/.s3cfg", False))],
)

# for CI, a fake .s3cfg should be created with access_key and secret_key at least
# otherwise, this test will not pass
def test_get_secrets(s3cfg_file: str, expected_res: bool):
    """Docstring to be added."""
    secrets = {
        "s3endpoint": None,
        "accesskey": None,
        "secretkey": None,
    }
    logger = logging.getLogger("s3_storage_handler_test")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.addHandler(logging.StreamHandler(sys.stdout))

    if "USER" in s3cfg_file:
        s3cfg_file = s3cfg_file.replace("USER", os.environ["USER"])

    assert expected_res == S3StorageHandler.get_secrets(secrets, s3cfg_file, logger)


@pytest.mark.unit
@pytest.mark.parametrize(
    "path, expected_res",
    [(("/usr/path/to/file", "file")), (("/usr/path/to/folder/", "folder"))],
)
def test_get_basename(path: str, expected_res: bool):
    """Docstring to be added."""
    assert expected_res == S3StorageHandler.get_basename(path)


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, bucket, nb_of_files",
    [
        (("http://localhost:5000", "test-bucket", 2012)),
        (("http://localhost:5000", "test-bucket", 999)),
        (("http://localhost:5000", "bucket-nonexistent", 0)),
    ],
)
def test_list_s3_files_obj(endpoint: str, bucket: str, nb_of_files: int):
    """Docstring to be added."""
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}
    logger = logging.getLogger("s3_storage_handler_test")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # create the test bucket

    server = ThreadedMotoServer()
    server.start()

    requests.post(endpoint + "/moto-api/reset", timeout=5)
    s3_handler = S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], secrets["region"])

    if s3_handler.check_bucket_access(bucket):
        server.stop()
        logger.error("The bucket %s does exist, for the tests it shouldn't", bucket)
        assert False
    if bucket == "test-bucket":
        s3_handler.s3_client.create_bucket(Bucket=bucket)
        for idx in range(nb_of_files):
            s3_handler.s3_client.put_object(Bucket=bucket, Key=f"test-dir/{idx}", Body="testing")
    # end of create
    s3_files, _ = s3_handler.list_s3_files_obj(bucket, "test-dir")
    server.stop()
    logger.debug("len(s3_files)  = %s", len(s3_files))
    assert len(s3_files) == nb_of_files


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
def test_files_to_be_downloaded(endpoint: str, bucket: str, lst_with_files: list, expected_res: list):
    """Docstring to be added."""
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}
    logger = logging.getLogger("s3_storage_handler_test")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.addHandler(logging.StreamHandler(sys.stdout))

    server = ThreadedMotoServer()
    server.start()
    requests.post(endpoint + "/moto-api/reset", timeout=5)
    s3_handler = S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], secrets["region"])
    if bucket == "test-bucket":
        s3_handler.s3_client.create_bucket(Bucket=bucket)
        for obj in expected_res:
            s3_handler.s3_client.put_object(Bucket=bucket, Key=obj[1], Body="testing")
    logger.debug("Bucket created !")
    collection = s3_handler.files_to_be_downloaded(bucket, lst_with_files)
    server.stop()
    assert len(Counter(collection) - Counter(expected_res)) == 0
    assert len(Counter(expected_res) - Counter(collection)) == 0


def cmp_dirs(dir1, dir2):
    """
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
        new_dir1 = os.path.join(dir1, common_dir)
        new_dir2 = os.path.join(dir2, common_dir)
        if not cmp_dirs(new_dir1, new_dir2):
            return False
    return True


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint, bucket, local_path, lst_with_files, lst_with_files_to_be_dwn, expected_res",
    [
        (
            (
                "http://localhost:5000",
                "test-bucket",
                "tmp_dwn_dir",
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
                "tmp_dwn_dir",
                ["nonexistent_1", "nonexistent_2/file1", "s3_storage_handler_test/no_root_file1"],
                [("", "s3_storage_handler_test/no_root_file1")],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "bucket-non-existent",
                "tmp_dwn_dir",
                ["nonexistent_1", "nonexistent_2/file1", "s3_storage_handler_test/no_root_file1"],
                [],
                [],
            )
        ),
    ],
)
async def test_prefect_download_files_from_s3(
    endpoint: str,
    bucket: str,
    local_path: str,
    lst_with_files: list,
    lst_with_files_to_be_dwn: list,
    expected_res: list,
):
    """Docstring to be added."""
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}

    short_s3_storage_handler_test_nb_of_files = 3
    logger = logging.getLogger("s3_storage_handler_test")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # create the test bucket
    server = ThreadedMotoServer()
    server.start()
    requests.post(endpoint + "/moto-api/reset", timeout=5)
    s3_handler = S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], secrets["region"])
    if bucket == "test-bucket":
        s3_handler.s3_client.create_bucket(Bucket=bucket)
        for obj in lst_with_files_to_be_dwn:
            s3_handler.s3_client.put_object(Bucket=bucket, Key=obj[1], Body="testing\n")
    # end of create

    collection = s3_handler.files_to_be_downloaded(bucket, lst_with_files)

    @flow
    async def test_flow():
        config = PrefectGetKeysFromS3Config(s3_handler,
                                            lst_with_files,
                                            bucket,
                                            local_path,
                                            0,
                                            True)
        state = await prefect_get_keys_from_s3(config, return_state=True)
        result = await state.result(fetch=True)
        return result

    res = await test_flow()
    logger.debug("Task returns: %s", res)
    server.stop()
    assert len(Counter(collection) - Counter(lst_with_files_to_be_dwn)) == 0
    assert len(Counter(lst_with_files_to_be_dwn) - Counter(collection)) == 0
    assert len(Counter(expected_res) - Counter(res)) == 0
    assert len(Counter(res) - Counter(expected_res)) == 0

    if bucket == "test-bucket":
        arr = os.getcwd().split("/")
        try:
            idx = arr.index("rs-server")
        except OSError:
            logger.error("Could not find the rs-server root path")
            assert False
        path_to_cmp_dirs = os.path.join("/", *(arr[:idx]), "rs-server/tests")
        try:
            if len(lst_with_files) > short_s3_storage_handler_test_nb_of_files:
                assert cmp_dirs(os.path.join(path_to_cmp_dirs, "full_s3_storage_handler_test"), local_path)
            else:
                assert cmp_dirs(os.path.join(path_to_cmp_dirs, "short_s3_storage_handler_test"), local_path)
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
                    "full_s3_storage_handler_test/no_root_file1",
                    "full_s3_storage_handler_test/no_root_file2",
                    "full_s3_storage_handler_test/subdir_1",
                    "full_s3_storage_handler_test/subdir_2",
                ],
                [
                    ("", "full_s3_storage_handler_test/no_root_file1"),
                    ("", "full_s3_storage_handler_test/no_root_file2"),
                    ("subdir_1", "full_s3_storage_handler_test/subdir_1/subdir_file"),
                    ("subdir_1/subsubdir_1", "full_s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file1"),
                    ("subdir_1/subsubdir_1", "full_s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file2"),
                    ("subdir_1/subsubdir_2", "full_s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file1"),
                    ("subdir_1/subsubdir_2", "full_s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file2"),
                    ("subdir_2", "full_s3_storage_handler_test/subdir_2/subdir_2_file1"),
                    ("subdir_2", "full_s3_storage_handler_test/subdir_2/subdir_2_file2"),
                ],
            )
        ),
        (
            (
                ["nonexistent_1", "nonexistent_2/file1", "full_s3_storage_handler_test/no_root_file1"],
                [
                    ("", "full_s3_storage_handler_test/no_root_file1"),
                ],
            )
        ),
    ],
)
def test_files_to_be_uploaded(lst_with_files: list, expected_res: list):
    """Docstring to be added."""
    secrets = {"s3endpoint": "http://localhost:5000", "accesskey": None, "secretkey": None, "region": ""}
    logger = logging.getLogger("s3_storage_handler_test")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.addHandler(logging.StreamHandler(sys.stdout))

    server = ThreadedMotoServer()
    server.start()
    s3_handler = S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], secrets["region"])
    server.stop()
    collection = s3_handler.files_to_be_uploaded(lst_with_files)
    logger.debug("collection   = %s", collection)
    logger.debug("expected_res = %s", expected_res)
    assert len(Counter(collection) - Counter(expected_res)) == 0
    assert len(Counter(expected_res) - Counter(collection)) == 0


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint, bucket, s3_prefix, lst_with_files, lst_with_files_to_be_up, keys_in_bucket, expected_res",
    [
        (
            (
                "http://localhost:5000",
                "test-bucket",
                "full_s3_storage_handler_test",
                [
                    "full_s3_storage_handler_test/no_root_file1",
                    "full_s3_storage_handler_test/no_root_file2",
                    "full_s3_storage_handler_test/subdir_1",
                    "full_s3_storage_handler_test/subdir_2",
                ],
                [
                    ("", "full_s3_storage_handler_test/no_root_file1"),
                    ("", "full_s3_storage_handler_test/no_root_file2"),
                    ("subdir_1", "full_s3_storage_handler_test/subdir_1/subdir_file"),
                    ("subdir_1/subsubdir_1", "full_s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file1"),
                    ("subdir_1/subsubdir_1", "full_s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file2"),
                    ("subdir_1/subsubdir_2", "full_s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file1"),
                    ("subdir_1/subsubdir_2", "full_s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file2"),
                    ("subdir_2", "full_s3_storage_handler_test/subdir_2/subdir_2_file1"),
                    ("subdir_2", "full_s3_storage_handler_test/subdir_2/subdir_2_file2"),
                ],
                [
                    "full_s3_storage_handler_test/no_root_file1",
                    "full_s3_storage_handler_test/no_root_file2",
                    "full_s3_storage_handler_test/subdir_1/subdir_file",
                    "full_s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file1",
                    "full_s3_storage_handler_test/subdir_1/subsubdir_1/subsubdir_file2",
                    "full_s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file1",
                    "full_s3_storage_handler_test/subdir_1/subsubdir_2/subsubdir_2_file2",
                    "full_s3_storage_handler_test/subdir_2/subdir_2_file1",
                    "full_s3_storage_handler_test/subdir_2/subdir_2_file2",
                ],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "test-bucket",
                "short_s3_storage_handler_test",
                ["nonexistent_1", "nonexistent_2/file1", "short_s3_storage_handler_test/no_root_file1"],
                [
                    ("", "short_s3_storage_handler_test/no_root_file1"),
                ],
                ["short_s3_storage_handler_test/no_root_file1"],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "bucket-nonexistent",
                "non_existent_dir",
                ["nonexistent_1", "nonexistent_2/file1", "short_s3_storage_handler_test/no_root_file1"],
                [("", "short_s3_storage_handler_test/no_root_file1")],
                [],
                ["short_s3_storage_handler_test/no_root_file1"],
            )
        ),
    ],
)
async def test_prefect_upload_files_to_s3(
    endpoint: str,
    bucket: str,
    s3_prefix: str,
    lst_with_files: list,
    lst_with_files_to_be_up: list,
    keys_in_bucket: list,
    expected_res: list,
):
    """Docstring to be added."""
    secrets = {"s3endpoint": endpoint, "accesskey": None, "secretkey": None, "region": ""}
    logger = logging.getLogger("s3_storage_handler_test")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.addHandler(logging.StreamHandler(sys.stdout))

    # create the test bucket
    server = ThreadedMotoServer()
    server.start()
    requests.post(endpoint + "/moto-api/reset", timeout=5)
    s3_handler = S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], secrets["region"])
    if bucket == "test-bucket":
        s3_handler.s3_client.create_bucket(Bucket=bucket)
    # end of create

    collection = s3_handler.files_to_be_uploaded(lst_with_files)
    logger.debug("collection              = {%s}", collection)
    logger.debug("lst_with_files_to_be_up = %s", lst_with_files_to_be_up)

    @flow
    async def test_flow():
        # logger = get_run_logger()
        config = PrefectPutFilesToS3Config(s3_handler,
                                            lst_with_files,
                                            bucket,
                                            s3_prefix,
                                            0,
                                            True)
        state = await prefect_put_files_to_s3(config, return_state=True)
        result = await state.result(fetch=True)
        # logger.debug("result = %s", result))
        return result

    res = await test_flow()
    test_bucket_files = []  # type: list[str]
    for key in lst_with_files:
        s3_files, _ = s3_handler.list_s3_files_obj(bucket, key)
        test_bucket_files = test_bucket_files + s3_files
        # if total == 0:
        #    break

    server.stop()
    logger.debug("test_bucket_files  = %s", test_bucket_files)
    # logger.debug("s3_files  = %s", s3_files))

    logger.debug("Task returns: %s", res)
    assert len(Counter(collection) - Counter(lst_with_files_to_be_up)) == 0
    assert len(Counter(lst_with_files_to_be_up) - Counter(collection)) == 0
    assert len(Counter(keys_in_bucket) - Counter(test_bucket_files)) == 0
    assert len(Counter(test_bucket_files) - Counter(keys_in_bucket)) == 0
    assert len(Counter(expected_res) - Counter(res)) == 0
    assert len(Counter(res) - Counter(expected_res)) == 0
