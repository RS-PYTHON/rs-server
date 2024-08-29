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

"""TODO Docstring to be added."""

import ntpath
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List

import boto3
import botocore
from rs_server_common.utils.logging import Logging

# seconds
DWN_S3FILE_RETRY_TIMEOUT = 6
DWN_S3FILE_RETRIES = 20
UP_S3FILE_RETRY_TIMEOUT = 6
UP_S3FILE_RETRIES = 20
SLEEP_TIME = 0.2
SET_PREFECT_LOGGING_LEVEL = "DEBUG"
S3_ERR_FORBIDDEN_ACCESS = 403
S3_ERR_NOT_FOUND = 404


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


class S3StorageHandler:
    """Interacts with an S3 storage

    S3StorageHandler for interacting with an S3 storage service.

    Attributes:
        access_key_id (str): The access key ID for S3 authentication.
        secret_access_key (str): The secret access key for S3 authentication.
        endpoint_url (str): The endpoint URL for the S3 service.
        region_name (str): The region name.
        s3_client (boto3.client): The s3 client to interact with the s3 storage
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

        self.access_key_id = access_key_id
        self.secret_access_key = secret_access_key
        self.endpoint_url = endpoint_url
        self.region_name = region_name
        self.s3_client: boto3.client = None
        self.connect_s3()
        self.logger.debug("S3StorageHandler created !")

    def __get_s3_client(self, access_key_id, secret_access_key, endpoint_url, region_name):
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
            retries={"total_max_attempts": 5},
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

        except Exception as e:
            self.logger.exception(f"Client error exception: {e}")
            raise RuntimeError("Client error exception ") from e

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
        if self.s3_client is None:
            return
        self.s3_client.close()
        self.s3_client = None

    def delete_file_from_s3(self, bucket, s3_obj):
        """Delete a file from S3.

        Args:
            bucket (str): The S3 bucket name.
            s3_obj (str): The S3 object key.

        Raises:
            RuntimeError: If an error occurs during the bucket access check.
        """
        if self.s3_client is None or bucket is None or s3_obj is None:
            raise RuntimeError("Input error for deleting the file")
        try:
            self.logger.info("Delete key s3://%s/%s", bucket, s3_obj)
            self.s3_client.delete_object(Bucket=bucket, Key=s3_obj)
        except botocore.client.ClientError as e:
            self.logger.exception(f"Failed to delete key s3://{bucket}/{s3_obj}: {e}")
            raise RuntimeError(f"Failed to delete key s3://{bucket}/{s3_obj}") from e
        except Exception as e:
            self.logger.exception(f"Failed to delete key s3://{bucket}/{s3_obj}: {e}")
            raise RuntimeError(f"Failed to delete key s3://{bucket}/{s3_obj}") from e

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
        with open(secret_file, "r", encoding="utf-8") as aws_credentials_file:
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
        list_with_files: List[Any] = []
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
            error_code = int(error.response["Error"]["Code"])
            if error_code == S3_ERR_FORBIDDEN_ACCESS:
                self.logger.exception((f"{bucket} is a private bucket. Forbidden access!"))
                raise RuntimeError(f"{bucket} is a private bucket. Forbidden access!") from error
            if error_code == S3_ERR_NOT_FOUND:
                self.logger.exception((f"{bucket} bucket does not exist!"))
                raise RuntimeError(f"{bucket} bucket does not exist!") from error
            self.logger.exception(f"Exception when checking the access to {bucket} bucket: {error}")
            raise RuntimeError(f"Exception when checking the access to {bucket} bucket") from error
        except botocore.exceptions.EndpointConnectionError as error:
            self.logger.exception(f"Could not connect to the endpoint when trying to access {bucket}: {error}")
            raise RuntimeError(f"Could not connect to the endpoint when trying to access {bucket}!") from error
        except Exception as error:
            self.logger.exception(f"General exception when trying to access bucket {bucket}: {error}")
            raise RuntimeError(f"General exception when trying to access bucket {bucket}") from error

    def check_s3_key_on_bucket(self, bucket, s3_key):
        """Check if the s3 key available in the bucket.

        Args:
            bucket (str): The S3 bucket name.
            s3_key (str): The s3 key that should be checked

        Raises:
            RuntimeError: If an error occurs during the bucket access check or if
            the s3_key is not available.
        """

        try:
            self.connect_s3()
            self.s3_client.head_object(Bucket=bucket, Key=s3_key)
        except botocore.client.ClientError as error:
            # check that it was a 404 vs 403 errors
            # If it was a 404 error, then the bucket does not exist.
            error_code = int(error.response["Error"]["Code"])
            if error_code == S3_ERR_FORBIDDEN_ACCESS:
                self.logger.exception((f"{bucket} is a private bucket. Forbidden access!"))
                raise RuntimeError(f"{bucket} is a private bucket. Forbidden access!") from error
            if error_code == S3_ERR_NOT_FOUND:
                self.logger.exception((f"The key s3://{bucket}/s3_key does not exist!"))
                # raise RuntimeError(f"The key s3://{bucket}/s3_key does not exist!") from error
                return False
            self.logger.exception(f"Exception when checking the access to key s3://{bucket}/{s3_key}: {error}")
            raise RuntimeError(f"Exception when checking the access to {bucket} bucket") from error
        except botocore.exceptions.EndpointConnectionError as error:
            self.logger.exception(f"Could not connect to the endpoint when trying to access {bucket}: {error}")
            raise RuntimeError(f"Could not connect to the endpoint when trying to access {bucket}!") from error
        except Exception as error:
            self.logger.exception(f"General exception when trying to access bucket {bucket}: {error}")
            raise RuntimeError(f"General exception when trying to access bucket {bucket}") from error
        return True

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
Couldn't get the s3 client. Retrying in %s seconds for %s more times",
                        s3_file,
                        DWN_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.wait_timeout(DWN_S3FILE_RETRY_TIMEOUT)

            if not downloaded:
                self.logger.error(
                    "Could not download the file %s. The download was \
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
            s3_obj = os.path.join(config.s3_path, collection_file[0], os.path.basename(file_to_be_uploaded).strip("/"))
            uploaded = False
            for keep_trying in range(config.max_retries):
                try:
                    # get the s3 client
                    self.connect_s3()
                    self.logger.info(
                        "Upload file %s to s3://%s/%s",
                        file_to_be_uploaded,
                        config.bucket,
                        s3_obj.lstrip("/"),
                    )

                    self.s3_client.upload_file(file_to_be_uploaded, config.bucket, s3_obj)
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
Couldn't get the s3 client. Retrying in %s seconds for %s more times",
                        file_to_be_uploaded,
                        UP_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.wait_timeout(UP_S3FILE_RETRY_TIMEOUT)

            if not uploaded:
                self.logger.error(
                    "Could not upload the file %s. The upload was \
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
                        self.logger.debug("Key deleted s3://%s/%s", config.bucket_src, collection_file[1])
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
Couldn't get the s3 client. Retrying in %s seconds for %s more times",
                        config.bucket_src,
                        collection_file[1],
                        config.bucket_dst,
                        DWN_S3FILE_RETRY_TIMEOUT,
                        config.max_retries - keep_trying,
                    )
                    self.wait_timeout(DWN_S3FILE_RETRY_TIMEOUT)

            if not copied:
                self.logger.error(
                    "Could not copy the file s3://%s/%s to s3://%s. The copy was \
retried for %s times. Aborting",
                    config.bucket_src,
                    collection_file[1],
                    config.bucket_dst,
                    config.max_retries,
                )
                failed_files.append(collection_file[1])

        return failed_files
