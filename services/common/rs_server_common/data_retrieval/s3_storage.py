"""This module is used to interact with an s3 storage."""
from pathlib import Path
from threading import Lock

import boto3

###########
# from .rs_server_common.utils.logging import Logging
########
import Logging
from botocore.exceptions import ClientError

from .storage import Storage


class S3StorageHandler(Storage):
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

    def login(self) -> None:
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

    def logout(self) -> None:
        """Close the connection to the S3 service."""
        if self.s3_client is not None:
            self.s3_client.close()
        self.s3_client = None

    def store(self, file: Path, location: Path) -> None:
        return super().store(file, location)

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
