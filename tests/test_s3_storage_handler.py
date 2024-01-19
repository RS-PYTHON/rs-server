"""Docstring to be added."""
# pylint: disable=R0913,R0914 # Too many arguments, Too many local variables
import filecmp
import os
import os.path as osp
import shutil
import tempfile
from collections import Counter

import pytest
import requests
import yaml
from moto.server import ThreadedMotoServer
from prefect import flow
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    PrefectGetKeysFromS3Config,
    PrefectPutFilesToS3Config,
    S3StorageHandler,
    prefect_get_keys_from_s3,
    prefect_put_files_to_s3,
)
from rs_server_common.utils.logging import Logging

# Resource folders specified from the parent directory of this current script
RSC_FOLDER = osp.realpath(osp.join(osp.dirname(__file__), "resources", "s3"))
FULL_FOLDER = osp.join(RSC_FOLDER, "full_s3_storage_handler_test")
SHORT_FOLDER = osp.join(RSC_FOLDER, "short_s3_storage_handler_test")


def export_aws_credentials():
    """Export AWS credentials as environment variables for testing purposes.

    This function sets the following environment variables with dummy values for AWS credentials:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_SECURITY_TOKEN
    - AWS_SESSION_TOKEN
    - AWS_DEFAULT_REGION

    Note: This function is intended for testing purposes only, and it should not be used in production.

    Returns:
        None

    Raises:
        None
    """
    with open(osp.join(RSC_FOLDER, "s3.yml"), "r", encoding="utf-8") as f:
        s3_config = yaml.safe_load(f)
        os.environ.update(s3_config["s3"])


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
    "s3cfg_file",
    [(("./USER/credentials_location/.s3cfg")), (("/path/to/none/.s3cfg"))],
)
def test_get_secrets(s3cfg_file: str):
    """Docstring to be added."""
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
                tmp.flush()
            S3StorageHandler.get_secrets(secrets, tmp_path)
        finally:
            os.remove(tmp_path)
    else:
        with pytest.raises(FileNotFoundError):
            S3StorageHandler.get_secrets(secrets, s3cfg_file)


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
        (("http://localhost:5000", "bucket-nonexistent", 0)),
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
    [(("http://localhost:5000", "test-bucket")), (("http://localhost:5000", "bucket-nonexistent"))],
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
@pytest.mark.asyncio
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
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "bucket-non-existent",
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
    lst_with_files: list,
    lst_with_files_to_be_dwn: list,
    expected_res: list,
):
    """test_prefect_download_files_from_s3 Function Documentation

    Test the prefect_download_files_from_s3 function.

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

        try:
            collection = s3_handler.files_to_be_downloaded(bucket, lst_with_files)
        except RuntimeError:
            collection = []
        local_path = tempfile.mkdtemp()

        @flow
        async def test_flow():
            config = PrefectGetKeysFromS3Config(
                s3_handler,
                lst_with_files,
                bucket,
                local_path,
                0,
                True,
                1,
            )  # type: ignore
            state = await prefect_get_keys_from_s3(config, return_state=True)  # type: ignore
            result = await state.result(fetch=True)  # type: ignore
            return result

        res = await test_flow()  # type: ignore
        logger.debug("Task returns: %s", res)
    except RuntimeError:
        res = []
    finally:
        server.stop()

    assert len(Counter(collection) - Counter(lst_with_files_to_be_dwn)) == 0
    assert len(Counter(lst_with_files_to_be_dwn) - Counter(collection)) == 0
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
    """Docstring to be added."""
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
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint, bucket, s3_prefix, lst_with_files, lst_with_files_to_be_up, keys_in_bucket, expected_res",
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
                [
                    ("", f"{SHORT_FOLDER}/no_root_file1"),
                ],
                [f"{SHORT_FOLDER}/no_root_file1"],
                [],
            )
        ),
        (
            (
                "http://localhost:5000",
                "bucket-nonexistent",
                "non_existent_dir",
                [
                    "nonexistent_1",
                    "nonexistent_2/file1",
                    f"{SHORT_FOLDER}/no_root_file1",
                ],
                [("", f"{SHORT_FOLDER}/no_root_file1")],
                [],
                [f"{SHORT_FOLDER}/no_root_file1"],
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
    """test_prefect_upload_files_to_s3 Function Documentation

    Test the files_to_be_uploaded method of the S3StorageHandler class.

    Parameters:
    - lst_with_files (list): List of local files to be checked for upload.
    - expected_res (list): List of tuples representing the expected files to be
    uploaded. Each tuple consists of a prefix and a file path.

    Raises:
    - AssertionError: If the result of S3StorageHandler.files_to_be_uploaded does not match expected_res.
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
        if bucket == "test-bucket":
            s3_handler.s3_client.create_bucket(Bucket=bucket)
        # end of create

        collection = s3_handler.files_to_be_uploaded(lst_with_files)
        logger.debug("collection              = {%s}", collection)
        logger.debug("lst_with_files_to_be_up = %s", lst_with_files_to_be_up)

        @flow
        async def test_flow():
            config = PrefectPutFilesToS3Config(s3_handler, lst_with_files, bucket, s3_prefix, 0, 1)
            state = await prefect_put_files_to_s3(config, return_state=True)  # type: ignore
            result = await state.result(fetch=True)  # type: ignore
            return result

        res = await test_flow()  # type: ignore
        test_bucket_files = []  # type: list[str]
        for key in lst_with_files:
            try:
                s3_files = s3_handler.list_s3_files_obj(bucket, key)
                test_bucket_files = test_bucket_files + s3_files
            except RuntimeError:
                pass
            # if total == 0:
            #    break
    finally:
        server.stop()

    logger.debug("test_bucket_files  = %s", test_bucket_files)

    logger.debug("Task returns: %s", res)
    assert len(Counter(collection) - Counter(lst_with_files_to_be_up)) == 0
    assert len(Counter(lst_with_files_to_be_up) - Counter(collection)) == 0
    assert len(Counter(keys_in_bucket) - Counter(test_bucket_files)) == 0
    assert len(Counter(test_bucket_files) - Counter(keys_in_bucket)) == 0
    assert len(Counter(expected_res) - Counter(res)) == 0
    assert len(Counter(res) - Counter(expected_res)) == 0
