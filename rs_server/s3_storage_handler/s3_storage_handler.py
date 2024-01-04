"""Docstring to be added."""
import ntpath
import os
import time
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any

import boto3
import botocore
from botocore.exceptions import ClientError
from prefect import exceptions, get_run_logger, task
from rs_server_common.utils.logging import Logging

# seconds
DWN_S3FILE_RETRY_TIMEOUT = 6
DWN_S3FILE_RETRIES = 20
UP_S3FILE_RETRY_TIMEOUT = 6
UP_S3FILE_RETRIES = 20
SET_PREFECT_LOGGING_LEVEL = "DEBUG"
S3_ERR_FORBIDDEN_ACCESS = 403
S3_ERR_NOT_FOUND = 404


class S3StorageHandler:
    """Interact with an S3 storage

    S3StorageHandler for interacting with an S3 storage service.

    Attributes:
        access_key_id (str): The access key ID for S3 authentication.
        secret_access_key (str): The secret access key for S3 authentication.
        endpoint_url (str): The endpoint URL for the S3 service.
        region_name (str): The region name.
    """

    def __init__(self, access_key_id, secret_access_key, endpoint_url, region_name):
        """Initialize the S3StorageHandler instance.

        Args:
            access_key_id (str): The access key ID for S3 authentication.
            secret_access_key (str): The secret access key for S3 authentication.
            endpoint_url (str): The endpoint URL for the S3 service.
            region_name (str): The region name.

        Raises:
            RuntimeError: If the connection to the S3 storage cannot be established.
        """
        self.logger = Logging.default(__name__)
        self.logger.debug("S3StorageHandler created !")

        self.s3_client_mutex = Lock()
        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.s3_client: boto3.client = None
        self.connect_s3()

    def __get_s3_client(self, access_key_id, secret_access_key, endpoint_url, region_name):
        """Retrieve or create an S3 client instance.

        Args:
            access_key_id (str): The access key ID for S3 authentication.
            secret_access_key (str): The secret access key for S3 authentication.
            endpoint_url (str): The endpoint URL for the S3 service.
            region_name (str): The region name.

        Returns:
            boto3.client: An S3 client instance.
        """
        # This mutex is needed in case of more threads accessing at the same time this function
        with self.s3_client_mutex:
            if self.s3_client:
                return self.s3_client
            client_config = botocore.config.Config(
                max_pool_connections=100,
                retries={"total_max_attempts": 10},
            )
            try:
                return boto3.client(
                    "s3",
                    aws_access_key_id=access_key_id,
                    aws_secret_access_key=secret_access_key,
                    endpoint_url=endpoint_url,
                    region_name=region_name,
                    config=client_config,
                )
            except ClientError as e:
                if e.response["Error"]["Code"] == "EntityAlreadyExists":
                    raise RuntimeError("This clent already exists") from e
                raise e  # for other errors, juste re-raise the exception

    def connect_s3(self):
        """Establish a connection to the S3 service.

        If the S3 client is not already instantiated, this method calls the private __get_s3_client
        method to create an S3 client instance using the provided credentials and configuration (see __init__).
        """
        if self.s3_client is None:
            self.s3_client = self.__get_s3_client(
                self.access_key_id,
                self.secret_access_key,
                self.endpoint_url,
                self.region_name,
            )

    def disconnect_s3(self):
        """Close the connection to the S3 service."""
        if self.s3_client is not None:
            self.s3_client.close()
        self.s3_client = None

    def delete_file_from_s3(self, bucket, s3_obj):
        """Delete a file from S3.

        Args:
            bucket (str): The S3 bucket name.
            s3_obj (str): The S3 object key.
        """
        if self.s3_client is None or bucket is None or s3_obj is None:
            raise RuntimeError("Input error for deleting the file")
        try:
            with self.s3_client_mutex:
                self.logger.debug("{%s} | {%s}", bucket, s3_obj)
                self.logger.info("Delete file s3://{%s}/{%s}", bucket, s3_obj)
                self.s3_client.delete_object(Bucket=bucket, Key=s3_obj)
        except ClientError as e:
            raise RuntimeError(f"Failed to delete file s3://{bucket}/{s3_obj}") from e

    # helper functions

    @staticmethod
    def get_secrets(secrets, secret_file):
        """Read secrets from a specified file.

        Usually it read the secrets from .s3cfg or aws credentials files
        Args:
            secrets (dict): Dictionary to store retrieved secrets.
            secret_file (str): Path to the file containing secrets.
            logger (Logger, optional): Logger instance for error logging.
        """
        dict_filled = 0
        with open(secret_file, "r", encoding="utf-8") as aws_credentials_file:
            lines = aws_credentials_file.readlines()
            for line in lines:
                if dict_filled == len(secrets):
                    break
                if secrets["s3endpoint"] is None and "host_bucket" in line:
                    dict_filled += 1
                    secrets["s3endpoint"] = line.strip().split("=")[1].strip()
                elif secrets["accesskey"] is None and "access_key" in line:
                    dict_filled += 1
                    secrets["accesskey"] = line.strip().split("=")[1].strip()
                elif secrets["secretkey"] is None and "secret_" in line and "_key" in line:
                    dict_filled += 1
                    secrets["secretkey"] = line.strip().split("=")[1].strip()
        if secrets["accesskey"] is None or secrets["secretkey"] is None:
            raise RuntimeError("Secret fields not found")

    @staticmethod
    def get_basename(input_path):
        """Get the filename from a full path.

        Args:
            int_path (str): The full path.

        Returns:
            str: The filename.
        """
        path, filename = ntpath.split(input_path)
        return filename or ntpath.basename(path)

    def files_to_be_downloaded(self, bucket, paths):
        """Create a list of S3 keys to be downloaded.

        The list will have the s3 keys to be downloaded from the bucket.
        It contains pairs (local_prefix_where_the_file_will_be_downloaded, full_s3_key_path)
        If a s3 key doesn't exist, the pair will be (None, requested_s3_key_path)

        Args:
            bucket (str): The S3 bucket name.
            paths (list): List of S3 object keys.

        Returns:
            list: List of tuples (local_prefix, full_s3_key_path).
        """
        # declaration of the list
        list_with_files = []
        # for each key, identify it as a file or a folder
        # in the case of a folder, the files will be recursively gathered
        for key in paths:
            path = key.strip().lstrip("/")
            s3_files = self.list_s3_files_obj(bucket, path)
            if len(s3_files) == 0:
                self.logger.warning("No key %s found.", path)
                continue
            self.logger.debug("total: %s | s3_files = %s", len(s3_files), s3_files)
            basename_part = self.get_basename(path)

            # check if it's a file or a dir
            if len(s3_files) == 1 and path == s3_files[0]:
                # the current key is a file, append it to the list
                list_with_files.append(("", s3_files[0]))
                self.logger.debug("Append files: list_with_files = %s", list_with_files)
            else:
                # the current key is a folder, append all its files (reursively gathered) to the list
                for s3_file in s3_files:
                    split = s3_file.split("/")
                    split_idx = split.index(basename_part)
                    list_with_files.append((os.path.join(*split[split_idx:-1]), s3_file.strip("/")))

        return list_with_files

    def files_to_be_uploaded(self, paths):
        """Creates a list of local files to be uploaded.

        The list contains pairs (s3_path, absolute_local_file_path)
        If the local file doesn't exist, the pair will be (None, requested_file_to_upload)

        Args:
            paths (list): List of local file paths.

        Returns:
            list: List of tuples (s3_path, absolute_local_file_path).
        """

        list_with_files = []
        for local in paths:
            path = local.strip()
            # check if it is a file
            self.logger.debug("path = %s", path)
            if os.path.isfile(path):
                self.logger.debug("Add %s", path)
                list_with_files.append(("", path))

            elif os.path.isdir(path):
                for root, dir_names, filenames in os.walk(path):
                    for file in filenames:
                        full_file_path = os.path.join(root, file.strip("/"))
                        self.logger.debug("full_file_path = %s | dir_names = %s", full_file_path, dir_names)
                        if not os.path.isfile(full_file_path):
                            continue
                        self.logger.debug(
                            "get_basename(path) = %s | root = %s | replace = %s",
                            self.get_basename(path),
                            root,
                            root.replace(path, ""),
                        )

                        keep_path = os.path.join(self.get_basename(path), root.replace(path, "").strip("/")).strip("/")
                        self.logger.debug("path = %s | keep_path = %s | root = %s", path, keep_path, root)

                        self.logger.debug("Add: %s | %s", keep_path, full_file_path)
                        list_with_files.append((keep_path, full_file_path))
            else:
                self.logger.warning("The path %s is not a directory nor a file, it will not be uploaded", path)

        return list_with_files

    def list_s3_files_obj(self, bucket, prefix):
        """Retrieve the content of an S3 directory.

        Args:
            bucket (str): The S3 bucket name.
            prefix (str): The S3 object key prefix.
            max_timestamp (datetime, optional): Maximum timestamp for file filtering.
            pattern (str, optional): Pattern to filter file names.

        Returns:
            list: List containing S3 object keys.
        """

        s3_files = []

        self.logger.warning("prefix = %s", prefix)
        try:
            with self.s3_client_mutex:
                paginator: Any = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
            for page in pages:
                for item in page.get("Contents", ()):
                    if item is not None:
                        s3_files.append(item["Key"])
        except Exception as error:
            raise RuntimeError(f"Listing files from s3://{bucket}/{prefix}") from error

        return s3_files

    @staticmethod
    def get_s3_data(s3_url):
        """
        Parses S3 URL to extract bucket, prefix, and file.

        Args:
            s3_url (str): The S3 URL.

        Returns:
            tuple: Tuple containing bucket, prefix, and file.
        """
        s3_data = s3_url.replace("s3://", "").split("/")
        bucket = ""
        start_idx = 0
        if s3_url.startswith("s3://"):
            bucket = s3_data[0]

            start_idx = 1
        prefix = ""
        if start_idx < len(s3_data):
            prefix = "/".join(s3_data[start_idx:-1])
        s3_file = s3_data[-1]
        return bucket, prefix, s3_file

    def check_bucket_access(self, bucket):
        """Check the accessibility of an S3 bucket.

        Args:
            bucket (str): The S3 bucket name.

        Raises:
            RuntimeError: If an error occurs during the bucket access check.
        """
        self.connect_s3()
        try:
            with self.s3_client_mutex:
                self.s3_client.head_bucket(Bucket=bucket)
        except botocore.client.ClientError as error:
            # check that it was a 404 vs 403 errors
            # If it was a 404 error, then the bucket does not exist.
            error_code = int(error.response["Error"]["Code"])
            if error_code == S3_ERR_FORBIDDEN_ACCESS:
                raise RuntimeError(f"{bucket} is a private bucket. Forbidden access!") from error
            if error_code == S3_ERR_NOT_FOUND:
                raise RuntimeError(f"{bucket} bucket does not exist!") from error


def wait_timeout(timeout):
    """
    Wait for a specified timeout duration.

    This function implements a simple timeout mechanism, where it sleeps for 0.2 seconds
    in each iteration until the cumulative sleep time reaches the specified timeout duration.

    Args:
        timeout (float): The total duration to wait in seconds.

    Returns:
        None

    Raises:
        None
    """
    time_cnt = 0.0
    while time_cnt < timeout:
        time.sleep(0.2)
        time_cnt += 0.2


def check_file_overwriting(local_file, overwrite, logger, idx):
    """Check whether a file already exists at the specified local path and handles overwriting.

    Parameters:
    - local_file (str): The local file path to check.
    - overwrite (bool): A flag indicating whether to overwrite the existing file if found.
    - logger (Logger): The logger object for logging messages.
    - idx (int): An index or identifier associated with the file.

    Returns:
    bool: True if overwriting is allowed or if the file doesn't exist, False otherwise.

    Raises:
    FileNotFoundError: If the specified local file does not exist.

    Example:
    ```python
    from logging import getLogger

    # Example usage
    logger = getLogger(__name__)
    file_path = "path/to/myfile.txt"
    can_overwrite = check_file_overwriting(file_path, True, logger, 1)
    if can_overwrite:
        # Proceed with file download or other operations
        pass
    ```

    Note:
    - If the file already exists and the overwrite flag is set to True, the function will log a message,
      delete the existing file, and return True.
    - If the file already exists and the overwrite flag is set to False, the function will log a warning
      message, and return False. In this case, the existing file won't be deleted.
    - If the file doesn't exist, the function will return True.

    """
    ret_overwrite = True
    if os.path.isfile(local_file):
        if overwrite:  # The file already exists, so delete it first
            logger.info(
                "Downloading task %s: File %s already exists. Deleting it before downloading",
                idx,
                S3StorageHandler.get_basename(local_file),
            )
            os.remove(local_file)
        else:
            logger.warning(
                "Downloading task %s: File %s already exists. Skipping it \
(use the overwrite flag if you want to overwrite this file)",
                idx,
                S3StorageHandler.get_basename(local_file),
            )
            ret_overwrite = False

    return ret_overwrite


@dataclass
class PrefectGetKeysFromS3Config:
    """S3 configuration for download

    Attributes:
        s3_storage_handler (S3StorageHandler): An instance of S3StorageHandler for S3 interactions.
        s3_files (list): A list of S3 object keys.
        bucket (str): The S3 bucket name.
        local_prefix (str): The local prefix where files will be downloaded.
        idx (int): An index used for debug. This is the index of the task launched from a prefect flow
        overwrite (bool, optional): Flag indicating whether to overwrite existing files. Default is False.
        max_retries (int, optional): The maximum number of download retries. Default is DWN_S3FILE_RETRIES.

    Methods:
        None
    """

    s3_storage_handler: S3StorageHandler
    s3_files: list
    bucket: str
    local_prefix: str
    idx: int
    overwrite: bool = False
    max_retries: int = DWN_S3FILE_RETRIES


@task
async def prefect_get_keys_from_s3(config: PrefectGetKeysFromS3Config) -> list:
    """Download S3 keys specified in the configuration.

    Args:
        config (PrefectGetKeysFromS3Config): Configuration for the S3 download.

    Returns:
        List[str]: A list with the S3 keys that couldn't be downloaded.

    Raises:
        Exception: Any unexpected exception raised during the download process.

    The function attempts to download files from S3 according to the provided configuration.
    It returns a list of S3 keys that couldn't be downloaded successfully.

    """
    try:
        logger = get_run_logger()
        logger.setLevel(SET_PREFECT_LOGGING_LEVEL)
    except exceptions.MissingContextError:
        logger = config.s3_storage_handler.logger
        logger.info("Could not get the prefect logger due to missing context")

    # collection_files: list of files to be downloaded
    #                   the list is formed from pair objects with the following
    #                   syntax: (local_path_to_be_added_to_the_local_prefix, s3_key)
    collection_files = config.s3_storage_handler.files_to_be_downloaded(config.bucket, config.s3_files)

    logger.debug("collection_files = %s | bucket = %s", collection_files, config.bucket)
    failed_files = []

    try:
        config.s3_storage_handler.check_bucket_access(config.bucket)
    except RuntimeError:
        logger.error(
            "Downloading task %s: Could not download the file(s) because the \
bucket %s does not exist or is not accessible. Aborting",
            config.idx,
            config.bucket,
        )
        for collection_file in collection_files:
            failed_files.append(collection_file[1])
        return failed_files

    for collection_file in collection_files:
        if collection_file[0] is None:
            failed_files.append(collection_file[1])
            continue

        keep_trying = 0
        local_path = os.path.join(config.local_prefix, collection_file[0].strip("/"))
        s3_file = collection_file[1]
        # for each file to download, create the local dir (if it does not exist)
        os.makedirs(local_path, exist_ok=True)
        # create the path for local file
        local_file = os.path.join(local_path, config.s3_storage_handler.get_basename(s3_file).strip("/"))

        if not check_file_overwriting(local_file, config.overwrite, logger, config.idx):
            continue
        # download the files while no external termination notice is received
        downloaded = False
        for keep_trying in range(config.max_retries):
            try:
                config.s3_storage_handler.connect_s3()
                dwn_start = datetime.now()
                config.s3_storage_handler.s3_client.download_file(config.bucket, s3_file, local_file)
                logger.debug(
                    "Downloading task %s: s3://%s/%s downloaded to %s in %s ms",
                    config.idx,
                    config.bucket,
                    s3_file,
                    local_file,
                    datetime.now() - dwn_start,
                )
                downloaded = True
                break
            except botocore.client.ClientError as error:
                logger.error(
                    "Downloading task %s: Error when downloading the file %s. \
Exception: %s. Retrying in %s seconds for %s more times",
                    config.idx,
                    s3_file,
                    error,
                    DWN_S3FILE_RETRY_TIMEOUT,
                    config.max_retries - keep_trying,
                )
                config.s3_storage_handler.disconnect_s3()
                wait_timeout(DWN_S3FILE_RETRY_TIMEOUT)
            except RuntimeError:
                logger.debug("3 config.s3_storage_handler.s3_client = %s", config.s3_storage_handler.s3_client)
                logger.error(
                    "Downloading task %s: Error when downloading the file %s. \
Couldn't get the s3 client. Retrying in %s seconds for %s more times",
                    config.idx,
                    s3_file,
                    DWN_S3FILE_RETRY_TIMEOUT,
                    config.max_retries - keep_trying,
                )
                wait_timeout(DWN_S3FILE_RETRY_TIMEOUT)

        if not downloaded:
            logger.error(
                "Downloading task %s: Could not download the file %s. The download was \
retried for %s times. Aborting",
                config.idx,
                s3_file,
                config.max_retries,
            )
            failed_files.append(s3_file)

    return failed_files


@dataclass
class PrefectPutFilesToS3Config:
    """Configuration for uploading files to S3.

    Attributes:
        s3_storage_handler (S3StorageHandler): An instance of S3StorageHandler for S3 interactions.
        files (List): A list of local file paths to be uploaded.
        bucket (str): The S3 bucket name.
        s3_path (str): The S3 path where files will be uploaded.
        idx (int): An index used for debug. This is the index of the task launched from a Prefect flow.
        max_retries (int, optional): The maximum number of upload retries. Default is UP_S3FILE_RETRIES.

    Methods:
        None
    """

    s3_storage_handler: S3StorageHandler
    files: list
    bucket: str
    s3_path: str
    idx: int
    max_retries: int = UP_S3FILE_RETRIES


@task
async def prefect_put_files_to_s3(config: PrefectPutFilesToS3Config) -> list:
    """Upload files to S3 according to the provided configuration.

    Args:
        config (PrefectPutFilesToS3Config): Configuration for the S3 upload.

    Returns:
        List[str]: A list with the local file paths that couldn't be uploaded.

    Raises:
        Exception: Any unexpected exception raised during the upload process.

    The function attempts to upload files to S3 according to the provided configuration.
    It returns a list of local files that couldn't be uploaded successfully.

    """
    try:
        logger = get_run_logger()
        logger.setLevel(SET_PREFECT_LOGGING_LEVEL)
    except exceptions.MissingContextError:
        logger = config.s3_storage_handler.logger
        logger.info("Could not get the prefect logger due to missing context")
    failed_files = []
    logger.debug("locals = %s", locals())

    collection_files = config.s3_storage_handler.files_to_be_uploaded(config.files)

    try:
        config.s3_storage_handler.check_bucket_access(config.bucket)
    except RuntimeError:
        logger.error(
            "Uploading task %s: Could not upload any of the received files because the \
bucket %s does not exist or is not accessible. Aborting",
            config.idx,
            config.bucket,
        )
        for collection_file in collection_files:
            failed_files.append(collection_file[1])
        return failed_files

    for collection_file in collection_files:
        if collection_file[0] is None:
            logger.error("The file %s can't be uploaded, its s3 prefix is None", collection_file[0])
            failed_files.append(collection_file[1])
            continue

        keep_trying = 0
        file_to_be_uploaded = collection_file[1]
        # create the s3 key
        s3_obj = os.path.join(config.s3_path, collection_file[0], os.path.basename(file_to_be_uploaded).strip("/"))
        uploaded = False
        for keep_trying in range(config.max_retries):
            try:
                # get the s3 client
                config.s3_storage_handler.connect_s3()
                logger.info(
                    "Uploading task %s: copy file %s to s3://%s/%s",
                    config.idx,
                    file_to_be_uploaded,
                    config.bucket,
                    s3_obj,
                )

                config.s3_storage_handler.s3_client.upload_file(file_to_be_uploaded, config.bucket, s3_obj)
                uploaded = True
                break
            except botocore.client.ClientError as error:
                logger.error(
                    "Uploading task %s: Error when uploading the file %s. \
Exception: %s. Retrying in %s seconds for %s more times",
                    config.idx,
                    file_to_be_uploaded,
                    error,
                    UP_S3FILE_RETRY_TIMEOUT,
                    config.max_retries - keep_trying,
                )
                config.s3_storage_handler.disconnect_s3()
                wait_timeout(UP_S3FILE_RETRY_TIMEOUT)
            except RuntimeError:
                logger.error(
                    "Uploading task %s: Error when uploading the file %s. \
Couldn't get the s3 client. Retrying in %s seconds for %s more times",
                    config.idx,
                    file_to_be_uploaded,
                    UP_S3FILE_RETRY_TIMEOUT,
                    config.max_retries - keep_trying,
                )
                wait_timeout(UP_S3FILE_RETRY_TIMEOUT)

        if not uploaded:
            logger.error(
                "Uploading task %s: Could not upload the file %s. The upload was \
    retried for %s times. Aborting",
                config.idx,
                file_to_be_uploaded,
                config.max_retries,
            )
            failed_files.append(file_to_be_uploaded)

    return failed_files
