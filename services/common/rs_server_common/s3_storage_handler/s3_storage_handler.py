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

"""Set of functions to connect to an S3 endpoint and run various operations."""

import asyncio
import concurrent.futures
import logging
import ntpath
import os
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import boto3
import botocore
import botocore.exceptions
import requests
from rs_server_common.utils.logging import Logging

# seconds
DWN_S3FILE_RETRY_TIMEOUT = 6
DWN_S3FILE_RETRIES = 20
UP_S3FILE_RETRY_TIMEOUT = 6
UP_S3FILE_RETRIES = 20
SLEEP_TIME = 0.2
S3_MAX_RETRIES = 3
S3_RETRY_TIMEOUT = 5
SET_PREFECT_LOGGING_LEVEL = "DEBUG"
S3_ERR_FORBIDDEN_ACCESS = "403"
S3_ERR_NOT_FOUND = "404"
HTTP_CONNECTION_TIMEOUT = 10
HTTP_READ_TIMEOUT = 120
PRESIGNED_URL_EXPIRATION_TIME = int(os.environ.get("RSPY_PRESIGNED_URL_EXPIRATION_TIME", "3600"))
# the maximum number of attempts that are made on a single request
# this defines the number of retries at the s3 protocol level
# there is also another retry mechanism set on the application level
# see functions like delete_file_from_s3 / get_keys_from_s3 / put_files_to_s3
S3_PROTOCOL_MAX_ATTEMPTS = 5

# The boto3 delete_objects function takes max 1000 items to delete.
MAX_DELETE_FILES = 1000


# pylint: disable=too-many-lines
@dataclass
class GetKeysFromS3Config:
    """S3 configuration for download

    Attributes:
        s3_files (list): A list with the  S3 object keys to be downloaded.
        bucket (str): The S3 bucket name.
        local_prefix (str): The local prefix where files will be downloaded.
        overwrite (bool, optional): Flag indicating whether to overwrite existing files. Default is False.
        max_retries (int, optional): The maximum number of download retries. Default is DWN_S3FILE_RETRIES.

    """

    s3_files: list
    bucket: str
    local_prefix: str
    overwrite: bool = False
    max_retries: int = DWN_S3FILE_RETRIES


@dataclass
class PutFilesToS3Config:
    """Configuration for uploading files to S3.

    Attributes:
        files (List): A list with the local file paths to be uploaded.
        bucket (str): The S3 bucket name.
        s3_path (str): The S3 path where files will be uploaded.
        max_retries (int, optional): The maximum number of upload retries. Default is UP_S3FILE_RETRIES.

    """

    files: list
    bucket: str
    s3_path: str
    max_retries: int = UP_S3FILE_RETRIES


@dataclass
class TransferFromS3ToS3Config:
    """S3 configuration for copying a list with keys between buckets

    Attributes:
        s3_files (list): A list with the S3 object keys to be copied.
        bucket_src (str): The source S3 bucket name.
        bucket_dst (str): The destination S3 bucket name.
        max_retries (int, optional): The maximum number of download retries. Default is DWN_S3FILE_RETRIES.

    """

    s3_files: list
    bucket_src: str
    bucket_dst: str
    copy_only: bool = False
    max_retries: int = DWN_S3FILE_RETRIES


class CustomSessionRedirect(requests.Session):
    """
    Custom session to handle HTTP 307 redirects and retain Authorization headers for allowed hosts.
    """

    def __init__(self, trusted_domains=list[str] | None):
        """
        Initialize the CustomSession instance.

        Args:
            trusted_domains (list): List of allowed hosts for redirection in case of change of protocol (HTTP <> HTTPS).
        """
        super().__init__()
        self.trusted_domains: list[str] = trusted_domains or []  # List of allowed hosts for redirection

    def should_strip_auth(self, old_url, new_url) -> bool:
        """
        Override the default behavior of stripping Authorization headers during redirection.

        Args:
            old_url (str): The URL of the original request.
            new_url (str): The URL to which the request is redirected.

        Returns:
            bool: Whether to strip Authorization headers (False to retain them).
        """
        old_parsed = urlparse(old_url)
        new_parsed = urlparse(new_url)

        # Check if the new host is in the allowed list
        # Also, include the original domain as an implicitly allowed domain
        if new_parsed.hostname == old_parsed.hostname or new_parsed.hostname in self.trusted_domains:
            # Allow protocol changes (HTTPS -> HTTP or vice versa) within the same or trusted hosts
            return False  # Do not strip auth

        return super().should_strip_auth(old_url, new_url)


class S3StorageHandler:
    """Interacts with an S3 storage

    S3StorageHandler for interacting with an S3 storage service.

    WARNING: THIS CLASS IS NOT THREAD-SAFE because of the connect_s3 and disconnect_s3 methods.

    Attributes:
        access_key_id (str): The access key ID for S3 authentication.
        secret_access_key (str): The secret access key for S3 authentication.
        endpoint_url (str): The endpoint URL for the S3 service.
        region_name (str): The region name.
        s3_client (boto3.client): The s3 client to interact with the s3 storage
    """

    def __init__(self, access_key_id=None, secret_access_key=None, endpoint_url=None, region_name=None):
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

        self.access_key_id = access_key_id or os.environ.get("S3_ACCESSKEY", "")
        self.secret_access_key = secret_access_key or os.environ.get("S3_SECRETKEY", "")
        self.endpoint_url = endpoint_url or os.environ.get("S3_ENDPOINT", "")
        self.region_name = region_name or os.environ.get("S3_REGION", "")
        self.s3_client: boto3.client = None
        self.connect_s3()
        # Suppress botocore debug messages
        logging.getLogger("botocore").setLevel(logging.INFO)
        logging.getLogger("boto3").setLevel(logging.INFO)
        logging.getLogger("urllib3").setLevel(logging.INFO)
        self.logger.debug("S3StorageHandler created !")

    def __get_s3_client(self):
        """Retrieve or create an S3 client instance.

        Args:
            access_key_id (str): The access key ID for S3 authentication.
            secret_access_key (str): The secret access key for S3 authentication.
            endpoint_url (str): The endpoint URL for the S3 service.
            region_name (str): The region name.

        Returns:
            client (boto3): An S3 client instance.
        """

        client_config = botocore.config.Config(
            max_pool_connections=100,
            # timeout for connection
            connect_timeout=5,
            # attempts in trying connection
            # note:  the default behaviour of boto3 is retrying
            # connections multiple times and exponentially backing off in between
            retries={"total_max_attempts": S3_PROTOCOL_MAX_ATTEMPTS},
        )
        try:
            return boto3.client(
                "s3",
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                endpoint_url=self.endpoint_url,
                region_name=self.region_name,
                config=client_config,
            )

        except Exception as e:
            self.logger.exception(f"Client error exception: {e}")
            raise RuntimeError("Client error exception ") from e

    def connect_s3(self):
        """Establish a connection to the S3 service.

        If the S3 client is not already instantiated, this method calls the private __get_s3_client
        method to create an S3 client instance using the provided credentials and configuration (see __init__).
        """
        if self.s3_client is None:
            self.s3_client = self.__get_s3_client()

    def disconnect_s3(self):
        """Close the connection to the S3 service."""
        if self.s3_client is None:
            return
        self.s3_client.close()
        self.s3_client = None

    def delete_file_from_s3(self, bucket, key, max_retries=S3_MAX_RETRIES):
        """Delete a file from S3.
        The functionality implies a retry mechanism at the application level, which is different
        than the retry mechanism from the s3 protocol level, with "retries" parameter from the s3 Config


        Args:
            bucket (str): The S3 bucket name.
            key (str): The S3 object key.

        Raises:
            RuntimeError: If an error occurs during the bucket access check.
        """
        if bucket is None or key is None:
            raise RuntimeError("Input error for deleting the file")
        attempt = 0
        while attempt < max_retries:
            try:
                self.connect_s3()
                self.logger.debug("Deleting s3 key s3://%s/%s", bucket, key)
                s3_key_exists, _ = self.check_s3_key_on_bucket(bucket, key)
                if not s3_key_exists:
                    self.logger.debug("S3 key to be deleted s3://%s/%s does not exist", bucket, key)
                    return
                self.s3_client.delete_object(Bucket=bucket, Key=key)
                self.logger.info("S3 key deleted: s3://%s/%s", bucket, key)
                return
            except (botocore.client.ClientError, botocore.exceptions.BotoCoreError) as e:
                attempt += 1
                if attempt < max_retries:
                    # keep retrying
                    self.disconnect_s3()
                    self.logger.error(
                        f"Failed to delete key s3://{bucket}/{key}: {e} \nRetrying in {S3_RETRY_TIMEOUT} seconds. ",
                    )
                    self.wait_timeout(S3_RETRY_TIMEOUT)
                    continue
                self.logger.exception(f"Failed to delete key s3://{bucket}/{key}. Reason: {e}")
                raise RuntimeError(f"Failed to delete key s3://{bucket}/{key}. Reason: {e}") from e
            except RuntimeError as e:
                self.logger.exception(f"Failed to check the key s3://{bucket}/{key}. Useless to retry. Reason: {e}")
                raise RuntimeError(
                    f"Failed to check the key s3://{bucket}/{key}. Useless to retry. Reason: {e}",
                ) from e
            except Exception as e:
                self.logger.exception(f"Failed to delete key s3://{bucket}/{key}. Reason: {e}")
                raise RuntimeError(f"Failed to delete key s3://{bucket}/{key}. Reason: {e}") from e

    def delete_files_from_s3(self, bucket: str, keys: list[str], max_retries: int = S3_MAX_RETRIES):
        """Delete a list of files from S3.
        The functionality implies a retry mechanism at the application level, which is different
        than the retry mechanism from the s3 protocol level, with "retries" parameter from the s3 Config

        Args:
            bucket (str): The S3 bucket name.
            keys (list[str]): The S3 object keys.

        Raises:
            RuntimeError: If an error occurs during the bucket access check.
        """
        if bucket is None or keys is None:
            raise RuntimeError("Input error for deleting the files")

        # NOTE: don't check if the files exist on the bucket.
        # If they don't, nothing happens, we don't have any error from boto3.
        self.logger.debug(f"Deleting {len(keys)} s3 keys from 's3://{bucket}'")

        attempt = 0
        while True:
            try:
                self.connect_s3()

                # Convert the key values into a dict
                key_dict = [{"Key": key} for key in keys]

                # The boto3 delete_objects function takes max 1000 items to delete.
                # Split the key list and process the chunks in parallel.
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures = [
                        executor.submit(
                            self.s3_client.delete_objects,
                            Bucket=bucket,
                            Delete={"Objects": key_dict[i : i + MAX_DELETE_FILES], "Quiet": True},
                        )
                        for i in range(0, len(keys), MAX_DELETE_FILES)
                    ]
                    for future in concurrent.futures.as_completed(futures):
                        future.result()

                # If everything went OK, exit the function
                return

            # Else handle retries
            except Exception as e:  # pylint: disable=broad-exception-caught
                attempt += 1
                message = f"Failed to delete keys from 's3://{bucket}':\n{traceback.format_exc()}"
                if attempt < max_retries:
                    # keep retrying
                    self.disconnect_s3()
                    self.logger.error(f"{message}\nRetrying in {S3_RETRY_TIMEOUT} seconds.")
                    self.wait_timeout(S3_RETRY_TIMEOUT)
                else:
                    self.logger.exception(message)
                    raise RuntimeError(message) from e

    async def adelete_files_from_s3(self, *args, **kwargs):
        """Async version of delete_files_from_s3. Call sync function in a separate thread."""
        return await asyncio.to_thread(self.delete_files_from_s3, *args, **kwargs)

    # helper functions

    @staticmethod
    def get_secrets_from_file(secrets, secret_file):
        """Read secrets from a specified file.

        It reads the secrets from .s3cfg or aws credentials files
        This function should not be used in production

        Args:
            secrets (dict): Dictionary to store retrieved secrets.
            secret_file (str): Path to the file containing secrets.
        """
        dict_filled = 0
        with open(secret_file, encoding="utf-8") as aws_credentials_file:
            lines = aws_credentials_file.readlines()
            for line in lines:
                if not secrets["s3endpoint"] and "host_bucket" in line:
                    dict_filled += 1
                    secrets["s3endpoint"] = line.strip().split("=")[1].strip()
                elif not secrets["accesskey"] and "access_key" in line:
                    dict_filled += 1
                    secrets["accesskey"] = line.strip().split("=")[1].strip()
                elif not secrets["secretkey"] and "secret_" in line and "_key" in line:
                    dict_filled += 1
                    secrets["secretkey"] = line.strip().split("=")[1].strip()
                if dict_filled == 3:
                    break

    @staticmethod
    def get_basename(input_path):
        """Get the filename from a full path.

        Args:
            input_path (str): The full path.

        Returns:
            filename (str): The filename.
        """
        path, filename = ntpath.split(input_path)
        return filename or ntpath.basename(path)

    @staticmethod
    def s3_path_parser(s3_url):
        """
        Parses S3 URL to extract bucket, prefix, and file.

        Args:
            s3_url (str): The S3 URL.

        Returns:
            (bucket, prefix, s3_file) (tuple): Tuple containing bucket, prefix, and file.
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

    def files_to_be_downloaded(self, bucket, paths):
        """Create a list with the S3 keys to be downloaded.

        The list will have the s3 keys to be downloaded from the bucket.
        It contains pairs (local_prefix_where_the_file_will_be_downloaded, full_s3_key_path)
        If a s3 key doesn't exist, the pair will be (None, requested_s3_key_path)

        Args:
            bucket (str): The S3 bucket name.
            paths (list): List of S3 object keys.

        Returns:
            list_with_files (list): List of tuples (local_prefix, full_s3_key_path).
        """
        # declaration of the list
        list_with_files: list[Any] = []
        # for each key, identify it as a file or a folder
        # in the case of a folder, the files will be recursively gathered
        for key in paths:
            path = key.strip().lstrip("/")
            s3_files = self.list_s3_files_obj(bucket, path)
            if len(s3_files) == 0:
                self.logger.warning("No key %s found.", path)
                list_with_files.append((None, path))
                continue
            self.logger.debug("total: %s | s3_files = %s", len(s3_files), s3_files)
            basename_part = self.get_basename(path)

            # check if it's a file or a dir
            if len(s3_files) == 1 and path == s3_files[0]:
                # the current key is a file, append it to the list
                list_with_files.append(("", s3_files[0]))
                self.logger.debug("Append files: list_with_files = %s", list_with_files)
            else:
                # the current key is a folder, append all its files (recursively gathered) to the list
                for s3_file in s3_files:
                    split = s3_file.split("/")
                    split_idx = split.index(basename_part)
                    list_with_files.append((os.path.join(*split[split_idx:-1]), s3_file.strip("/")))

        return list_with_files

    def files_to_be_uploaded(self, paths):
        """Creates a list with the local files to be uploaded.

        The list contains pairs (s3_path, absolute_local_file_path)
        If the local file doesn't exist, the pair will be (None, requested_file_to_upload)

        Args:
            paths (list): List of local file paths.

        Returns:
            list_with_files (list): List of tuples (s3_path, absolute_local_file_path).
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

        Returns:
            s3_files (list): List containing S3 object keys.
        """

        s3_files = []

        try:
            paginator: Any = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
            for page in pages:
                for item in page.get("Contents", ()):
                    if item is not None:
                        s3_files.append(item["Key"])
        except Exception as error:
            self.logger.exception(f"Exception when trying to list files from s3://{bucket}/{prefix}: {error}")
            raise RuntimeError(f"Listing files from s3://{bucket}/{prefix}") from error

        return s3_files

    def check_bucket_access(self, bucket):
        """Check the accessibility of an S3 bucket.

        Args:
            bucket (str): The S3 bucket name.

        Raises:
            RuntimeError: If an error occurs during the bucket access check.
        """

        try:
            self.connect_s3()
            self.s3_client.head_bucket(Bucket=bucket)
        except botocore.client.ClientError as error:
            # check that it was a 404 vs 403 errors
            # If it was a 404 error, then the bucket does not exist.
            error_code = error.response["Error"]["Code"]
            if error_code == S3_ERR_FORBIDDEN_ACCESS:
                self.logger.exception(f"{bucket} is a private bucket. Forbidden access!")
                raise RuntimeError(f"{bucket} is a private bucket. Forbidden access!") from error
            if error_code == S3_ERR_NOT_FOUND:
                self.logger.exception(f"{bucket} bucket does not exist!")
                raise RuntimeError(f"{bucket} bucket does not exist!") from error
            self.logger.exception(f"Exception when checking the access to {bucket} bucket: {error}")
            raise RuntimeError(f"Exception when checking the access to {bucket} bucket") from error
        except botocore.exceptions.EndpointConnectionError as error:
            self.logger.exception(f"Failed to connect to the endpoint when trying to access {bucket}: {error}")
            raise RuntimeError(f"Failed to connect to the endpoint when trying to access {bucket}!") from error
        except Exception as error:
            self.logger.exception(f"General exception when trying to access bucket {bucket}: {error}")
            raise RuntimeError(f"General exception when trying to access bucket {bucket}") from error

    def check_s3_key_on_bucket(self, bucket, s3_key):
        """Check if the s3 key is available in the bucket.

        Args:
            bucket (str): The S3 bucket name.
            s3_key (str): The s3 key that should be checked

        Returns: True and size if the s3 key is available, False and -1 and it isn't

        Raises:
            RuntimeError: If an error occurs during the bucket access check or if
                the s3_key is not available.
        """
        size = -1
        try:
            self.connect_s3()
            self.logger.debug(f"Checking for the presence of the s3 key s3://{bucket}/{s3_key}")
            response = self.s3_client.head_object(Bucket=bucket, Key=s3_key)
            # get the size of the file as well
            if isinstance(response, dict):
                size = response.get("ContentLength", -1)
        except botocore.client.ClientError as error:
            # check that it was a 404 vs 403 errors
            # If it was a 404 error, then the bucket does not exist.
            error_code = error.response["Error"]["Code"]
            if error_code == S3_ERR_FORBIDDEN_ACCESS:
                self.logger.exception(f"{bucket} is a private bucket. Forbidden access!")
                raise RuntimeError(f"{bucket} is a private bucket. Forbidden access!") from error
            if error_code == S3_ERR_NOT_FOUND:
                self.logger.exception(f"The key s3://{bucket}/{s3_key} does not exist!")
                return False, size
            self.logger.exception(f"Exception when checking the access to key s3://{bucket}/{s3_key}: {error}")
            raise RuntimeError(f"Exception when checking the access to {bucket} bucket") from error
        except (
            botocore.exceptions.EndpointConnectionError,
            botocore.exceptions.NoCredentialsError,
            botocore.exceptions.PartialCredentialsError,
        ) as error:
            self.logger.exception(f"Failed to connect to the endpoint when trying to access {bucket}: {error}")
            raise RuntimeError(f"Failed to connect to the endpoint when trying to access {bucket}!") from error
        except Exception as error:
            self.logger.exception(f"General exception when trying to access bucket {bucket}: {error}")
            raise RuntimeError(f"General exception when trying to access bucket {bucket}") from error

        return True, size

    def wait_timeout(self, timeout):
        """
        Wait for a specified timeout duration (minimum 200 ms).

        This function implements a simple timeout mechanism, where it sleeps for 0.2 seconds
        in each iteration until the cumulative sleep time reaches the specified timeout duration.

        Args:
            timeout (float): The total duration to wait in seconds.

        """
        time_cnt = 0.0
        while time_cnt < timeout:
            time.sleep(SLEEP_TIME)
            time_cnt += SLEEP_TIME

    def check_file_overwriting(self, local_file, overwrite):
        """Check if file exists and determine if it should be overwritten.

        Args:
            local_file (str): Path to the local file.
            overwrite (bool): Whether to overwrite the existing file.

        Returns:
            bool (bool): True if the file should be overwritten, False otherwise.

        Note:
        - If the file already exists and the overwrite flag is set to True, the function logs a message,
        deletes the existing file, and returns True.
        - If the file already exists and the overwrite flag is set to False, the function logs a warning
        message, and returns False. In this case, the existing file won't be deleted.
        - If the file doesn't exist, the function returns True.

        """
        if os.path.isfile(local_file):
            if overwrite:  # The file already exists, so delete it first
                self.logger.info(
                    "File %s already exists. Deleting it before downloading",
                    S3StorageHandler.get_basename(local_file),
                )
                os.remove(local_file)
            else:
                self.logger.warning(
                    "File %s already exists. Ignoring (use the overwrite flag if you want to overwrite this file)",
                    S3StorageHandler.get_basename(local_file),
                )
                return False

        return True

    def get_keys_from_s3(self, config: GetKeysFromS3Config) -> list:
        """Download S3 keys specified in the configuration.

        Args:
            config (GetKeysFromS3Config): Configuration for the S3 download.

        Returns:
            List[str]: A list with the S3 keys that couldn't be downloaded.

        Raises:
            Exception: Any unexpected exception raised during the download process.

        The function attempts to download files from S3 according to the provided configuration.
        It returns a list of S3 keys that couldn't be downloaded successfully.

        """

        # check the access to the bucket first, or even if it does exist
        self.check_bucket_access(config.bucket)

        # collection_files: list of files to be downloaded
        #                   the list contains pair objects with the following
        #                   syntax: (local_path_to_be_added_to_the_local_prefix, s3_key)
        #                   the local_path_to_be_added_to_the_local_prefix may be none if the file doesn't exist
        collection_files = self.files_to_be_downloaded(config.bucket, config.s3_files)

        self.logger.debug("collection_files = %s | bucket = %s", collection_files, config.bucket)
        failed_files = []

        for collection_file in collection_files:
            if collection_file[0] is None:
                failed_files.append(collection_file[1])
                continue

            local_path = os.path.join(config.local_prefix, collection_file[0].strip("/"))
            s3_file = collection_file[1]
            # for each file to download, create the local dir (if it does not exist)
            os.makedirs(local_path, exist_ok=True)
            # create the path for local file
            local_file = os.path.join(local_path, self.get_basename(s3_file).strip("/"))

            if not self.check_file_overwriting(local_file, config.overwrite):
                continue
            # download the files
            downloaded = False
            for keep_trying in range(config.max_retries):
                try:
                    self.connect_s3()
                    dwn_start = datetime.now()
                    self.s3_client.download_file(config.bucket, s3_file, local_file)
                    self.logger.debug(
                        "s3://%s/%s downloaded to %s in %s ms",
                        config.bucket,
                        s3_file,
                        local_file,
                        datetime.now() - dwn_start,
                    )
                    downloaded = True
                    break
                except (botocore.client.ClientError, botocore.exceptions.EndpointConnectionError) as error:
                    self.logger.exception(
                        "Error when downloading the file %s. \
Exception: %s. Retrying in %s seconds for %s more times",
                        s3_file,
                        error,
                        DWN_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.disconnect_s3()
                    self.wait_timeout(DWN_S3FILE_RETRY_TIMEOUT)
                except RuntimeError:
                    self.logger.exception(
                        "Error when downloading the file %s. \
Failed to get the s3 client. Retrying in %s seconds for %s more times",
                        s3_file,
                        DWN_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.wait_timeout(DWN_S3FILE_RETRY_TIMEOUT)

            if not downloaded:
                self.logger.error(
                    "Failed to download the file %s. The download was \
retried for %s times. Aborting",
                    s3_file,
                    config.max_retries,
                )
                failed_files.append(s3_file)

        return failed_files

    def put_files_to_s3(self, config: PutFilesToS3Config) -> list:
        """Upload files to S3 according to the provided configuration.

        Args:
            config (PutFilesToS3Config): Configuration for the S3 upload.

        Returns:
            List[str]: A list with the local file paths that couldn't be uploaded.

        Raises:
            Exception: Any unexpected exception raised during the upload process.

        The function attempts to upload files to S3 according to the provided configuration.
        It returns a list of local files that couldn't be uploaded successfully.

        """

        # check the access to the bucket first, or even if it does exist
        self.check_bucket_access(config.bucket)

        collection_files = self.files_to_be_uploaded(config.files)
        failed_files = []

        for collection_file in collection_files:
            if collection_file[0] is None:
                self.logger.error("The file %s can't be uploaded, its s3 prefix is None", collection_file[0])
                failed_files.append(collection_file[1])
                continue

            file_to_be_uploaded = collection_file[1]
            # create the s3 key
            key = os.path.join(config.s3_path, collection_file[0], os.path.basename(file_to_be_uploaded).strip("/"))
            uploaded = False
            for keep_trying in range(config.max_retries):
                try:
                    # get the s3 client
                    self.connect_s3()
                    self.logger.info(
                        "Upload file %s to s3://%s/%s",
                        file_to_be_uploaded,
                        config.bucket,
                        key.lstrip("/"),
                    )

                    self.s3_client.upload_file(file_to_be_uploaded, config.bucket, key)
                    uploaded = True
                    break
                except (
                    botocore.client.ClientError,
                    botocore.exceptions.EndpointConnectionError,
                    boto3.exceptions.S3UploadFailedError,
                ) as error:
                    self.logger.exception(
                        "Error when uploading the file %s. \
Exception: %s. Retrying in %s seconds for %s more times",
                        file_to_be_uploaded,
                        error,
                        UP_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.disconnect_s3()
                    self.wait_timeout(UP_S3FILE_RETRY_TIMEOUT)
                except RuntimeError:
                    self.logger.exception(
                        "Error when uploading the file %s. \
Failed to get the s3 client. Retrying in %s seconds for %s more times",
                        file_to_be_uploaded,
                        UP_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.wait_timeout(UP_S3FILE_RETRY_TIMEOUT)

            if not uploaded:
                self.logger.error(
                    "Failed to upload the file %s. The upload was \
retried for %s times. Aborting",
                    file_to_be_uploaded,
                    config.max_retries,
                )
                failed_files.append(file_to_be_uploaded)

        return failed_files

    def transfer_from_s3_to_s3(self, config: TransferFromS3ToS3Config) -> list:
        """Copy S3 keys specified in the configuration.
        Args:
            config (TransferFromS3ToS3Config): Configuration object containing bucket source, bucket destination,
                      S3 files, maximum retries.

        Returns:
            list: A list of S3 keys that failed to be copied.

        Raises:
            Exception: Any unexpected exception raised during the upload process.
        """
        # check the access to both buckets first, or even if they do exist
        self.check_bucket_access(config.bucket_src)
        self.check_bucket_access(config.bucket_dst)

        # collection_files: list of files to be downloaded
        #                   the list contains pair objects with the following
        #                   syntax: (local_path_to_be_added_to_the_local_prefix, s3_key)

        collection_files = self.files_to_be_downloaded(config.bucket_src, config.s3_files)

        self.logger.debug("collection_files = %s | bucket = %s", collection_files, config.bucket_src)
        failed_files = []
        copy_src = {"Bucket": config.bucket_src, "Key": ""}

        for collection_file in collection_files:
            if collection_file[0] is None:
                failed_files.append(collection_file[1])
                continue

            copied = False
            for keep_trying in range(config.max_retries):
                self.logger.debug(
                    "keep_trying %s | range(config.max_retries) %s ",
                    keep_trying,
                    range(config.max_retries),
                )
                try:
                    self.connect_s3()
                    dwn_start = datetime.now()
                    copy_src["Key"] = collection_file[1]
                    self.logger.debug("copy_src = %s", copy_src)
                    self.s3_client.copy_object(CopySource=copy_src, Bucket=config.bucket_dst, Key=collection_file[1])
                    self.logger.debug(
                        "s3://%s/%s copied to s3://%s/%s in %s ms",
                        config.bucket_src,
                        collection_file[1],
                        config.bucket_dst,
                        collection_file[1],
                        datetime.now() - dwn_start,
                    )
                    if not config.copy_only:
                        self.delete_file_from_s3(config.bucket_src, collection_file[1])
                    copied = True
                    break
                except (botocore.client.ClientError, botocore.exceptions.EndpointConnectionError) as error:
                    self.logger.exception(
                        "Error when copying the file s3://%s/%s to s3://%s. \
Exception: %s. Retrying in %s seconds for %s more times",
                        config.bucket_src,
                        collection_file[1],
                        config.bucket_dst,
                        error,
                        DWN_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.disconnect_s3()
                    self.wait_timeout(DWN_S3FILE_RETRY_TIMEOUT)
                except RuntimeError:
                    self.logger.exception(
                        "Error when copying the file s3://%s/%s to s3://%s. \
Failed to get the s3 client. Retrying in %s seconds for %s more times",
                        config.bucket_src,
                        collection_file[1],
                        config.bucket_dst,
                        DWN_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.wait_timeout(DWN_S3FILE_RETRY_TIMEOUT)

            if not copied:
                self.logger.error(
                    "Failed to copy the file s3://%s/%s to s3://%s. The copy was \
retried for %s times. Aborting",
                    config.bucket_src,
                    collection_file[1],
                    config.bucket_dst,
                    config.max_retries,
                )
                failed_files.append(collection_file[1])

        return failed_files

    def s3_streaming_upload(self, request: requests.Request, trusted_domains: list[str], bucket: str, key: str):
        """
        Upload a file to an S3 bucket using HTTP byte-streaming with retries.

        This method retrieves data from `stream_url` in chunks and uploads it to the specified S3 bucket
        (`bucket`) under the specified key (`key`). It includes retry logic for network and S3 client errors,
        with exponential backoff between retries. The method handles errors during both the HTTP request and the
        S3 upload process, raising a `RuntimeError` if the retries are exhausted without success.

        Args:
            stream_url (str): The URL of the file to be streamed and uploaded.
            trusted_domains (list): List of allowed hosts for redirection in case of change of protocol (HTTP <> HTTPS).
            auth (Any): Authentication credentials for the HTTP request (if required).
            bucket (str): The name of the target S3 bucket.
            key (str): The S3 object key (file path) to store the streamed file.

        Raises:
            ConnectionError: If there is a failure due to the HTTP request or the S3 upload
            RuntimeError: If any unhandled exception is caught.

        Exception Handling:
            - HTTP errors such as timeouts or bad responses (4xx, 5xx) are handled using
                `requests.exceptions.RequestException`.
            - S3 client errors such as `ClientError` and `BotoCoreError` are captured, logged, and retried.
            - Any other unexpected errors are caught and re-raised as `RuntimeError`.
        """
        if bucket is None or key is None:
            raise RuntimeError(f"Input error for streaming the file from {request.url} to s3://{bucket}/{key}")
        timeout: tuple[int, int] = (HTTP_CONNECTION_TIMEOUT, HTTP_READ_TIMEOUT)

        try:
            session = CustomSessionRedirect(trusted_domains)
            self.logger.debug(f"trusted_domains = {trusted_domains}")
            prepared_request = session.prepare_request(request)
            self.connect_s3()
            self.logger.info(f"Starting the streaming of {request.url} to s3://{bucket}/{key}")
            with session.send(prepared_request, stream=True, timeout=timeout) as response:
                self.logger.debug(f"Request headers: {response.request.headers}")
                response.raise_for_status()  # Raise an error for bad responses (4xx and 5xx)

                # Default chunksize is set to 64Kb, can be manually increased
                chunk_size = 64 * 1024  # 64kb
                with response.raw as data_stream:
                    self.s3_client.upload_fileobj(
                        data_stream,
                        bucket,
                        key,
                        Config=boto3.s3.transfer.TransferConfig(multipart_threshold=chunk_size * 2),
                    )
                self.logger.info(f"Successfully uploaded to s3://{bucket}/{key}")
        except (
            requests.exceptions.RequestException,
            botocore.client.ClientError,
            botocore.exceptions.BotoCoreError,
        ) as e:
            self.logger.exception(f"Failed to stream the file from {request.url} to s3://{bucket}/{key}: {e}.")
            raise ConnectionError(f"Failed to stream the file from {request.url} to s3://{bucket}/{key}: {e}.") from e
        except Exception as e:
            self.logger.exception(
                f"General exception.\nFailed to stream the file from {request.url} to s3://{bucket}/{key}: {e}",
            )
            raise RuntimeError(
                f"General exception.\nFailed to stream the file from {request.url} to s3://{bucket}/{key}: {e}",
            ) from e

    def s3_streaming_from_http(
        self,
        stream_url: str,
        trusted_domains: list[str],
        auth: Any,
        bucket: str,
        key: str,
    ):
        """
        Upload a file from an http source to an S3 bucket.

        Args:
            stream_url (str): The URL of the file to be streamed and uploaded.
            trusted_domains (list): List of allowed hosts for redirection in case of change of protocol (HTTP <> HTTPS).
            auth (Any): Authentication credentials for the HTTP request (if required).
            bucket (str): The name of the target S3 bucket.
            key (str): The S3 object key (file path) to store the streamed file.
        """
        # Prepare the request
        request = requests.Request(
            method="GET",
            url=stream_url,
            auth=auth,
        )

        # Start streaming with formatted request
        self.s3_streaming_upload(request, trusted_domains, bucket, key)

    def s3_streaming_from_s3(
        self,
        source_url: str,
        source_endpoint_url: str,
        source_access_key: str,
        source_secret_key: str,
        destination_bucket: str,
        destination_key: str,
        trusted_domains: list[str],
    ):
        """
        Upload a file from an external S3 bucket to an S3 bucket.

        Args:
            stream_url (str): Source URL for the item to upload (contains bucket name and item key).
            source_endpoint_url (str): Endpoint URL of the source S3 bucket.
            source_access_key (str): Access key to the external S3 bucket.
            source_secret_key (str): Secret key to the external S3 bucket.
            destination_bucket (str): The name of the target S3 bucket.
            destination_key (str): The S3 object key (file path) to store the streamed file.
            trusted_domains (list): List of allowed hosts for redirection in case of change of protocol (HTTP <> HTTPS).
        """
        # Format input values
        if not source_url.startswith("s3://"):
            raise ValueError(
                f"Wrong source URL for S3 to S3 streaming (expected URL starting with 's3://', got '{source_url}').",
            )
        source_url = source_url.removeprefix("s3://")
        source_params = {"Bucket": source_url.split("/", 1)[0], "Key": source_url.split("/", 1)[1]}

        # Connect to external s3 to generate URL
        try:
            source_s3_client = boto3.client(
                "s3",
                endpoint_url=source_endpoint_url,
                aws_access_key_id=source_access_key,
                aws_secret_access_key=source_secret_key,
                use_ssl=True,
            )
            presigned_url = source_s3_client.generate_presigned_url(
                "get_object",
                Params=source_params,
                ExpiresIn=PRESIGNED_URL_EXPIRATION_TIME,
            )
        except (botocore.exceptions.BotoCoreError, botocore.exceptions.ClientError) as error:
            self.logger.error(f"Failed to connect to external s3 endpoint {source_endpoint_url}: {error}.")
            raise ConnectionError(
                f"Failed to connect to external s3 endpoint {source_endpoint_url}: {error}.",
            ) from error

        # Prepare the request
        request = requests.Request(
            method="GET",
            url=presigned_url,
        )

        # Start streaming with formatted request
        self.s3_streaming_upload(request, trusted_domains, destination_bucket, destination_key)
