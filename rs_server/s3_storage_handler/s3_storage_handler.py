"""Docstring to be added."""
import ntpath
import os
import sys
import traceback
from threading import Lock

import boto3
import botocore

# seconds
DWN_S3FILE_RETRY_TIMEOUT = 6
DWN_S3FILE_RETRIES = 20
UP_S3FILE_RETRY_TIMEOUT = 6
UP_S3FILE_RETRIES = 20
SET_PREFECT_LOGGING_LEVEL = "DEBUG"
S3_ERR_FORBIDDEN_ACCESS = 403
S3_ERR_NOT_FOUND = 404

s3_client_mutex = Lock()


# get the s3 handler
def get_s3_client():
    """Docstring to be added."""
    # This mutex is needed in case of more threads accessing at the same time this function
    s3_client_mutex.acquire()
    client_config = botocore.config.Config(
        max_pool_connections=100,
        retries=dict(total_max_attempts=10),
    )
    s3_client = None
    try:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
            endpoint_url=os.environ["S3_ENDPOINT"],
            region_name=os.environ["S3_REGION"],
            config=client_config,
        )
    except Exception as e:
        print(e)
        s3_client_mutex.release()
        return None

    s3_client_mutex.release()
    return s3_client


# delete a file from s3 by using the s3 handler
def delete_file_from_s3(s3_client, bucket, s3_obj):
    """Docstring to be added."""
    if s3_client is None or bucket is None or s3_obj is None:
        print("Input error for deleting the file")
        return False
    try:
        print("{} | {}".format(bucket, s3_obj))
        print("Trying to delete file s3://{}/{}".format(bucket, s3_obj))
        s3_client.delete_object(Bucket=bucket, Key=s3_obj)
    except Exception as e:
        tb = traceback.format_exc()
        print("Failed to delete file s3://{}/{}".format(bucket, s3_obj))
        print("Exception: {} | {}".format(e, tb))
        return False
    return True


# helper functions
# function to read the secrets from .s3cfg or aws credentials files
def get_secrets(secrets, secret_file, logger=None):
    """Docstring to be added."""
    try:
        with open(secret_file, "r") as aws_credentials_file:
            lines = aws_credentials_file.readlines()
            for line in lines:
                if secrets["accesskey"] is not None and secrets["secretkey"] is not None:
                    break
                if secrets["s3endpoint"] is None and "host_bucket" in line:
                    secrets["s3endpoint"] = line.strip().split("=")[1].strip()
                if secrets["accesskey"] is None and "access_key" in line:
                    secrets["accesskey"] = line.strip().split("=")[1].strip()
                if secrets["secretkey"] is None and "secret_" in line and "_key" in line:
                    secrets["secretkey"] = line.strip().split("=")[1].strip()
    except Exception as e:
        if logger:
            logger.error("Could not get the secrets, exception: {}".format(e))
        else:
            print("Could not get the secrets, exception: {}".format(e))
        return False
    if secrets["accesskey"] is None or secrets["secretkey"] is None:
        return False
    return True


# get the filename only from a full path to it
def get_basename(input_path):
    """Docstring to be added."""
    path, filename = ntpath.split(input_path)
    return filename or ntpath.basename(path)


# creates the list with s3 keys to be downloaded from the bucket
# the list should contains pairs (local_prefix_where_the_file_will_be_downloaded, full_s3_key_path)
# if a s3 key doesn't exist, the pair will be (None, requested_s3_key_path)
def files_to_be_downloaded(bucket, paths, logger):
    """Docstring to be added."""
    if logger is None:
        print("files_to_be_downloaded func: No logger object provided")
        sys.exit(-1)

    s3_client = get_s3_client()
    if s3_client is None:
        logger.error("Could not get the s3 handler")
        return False

    # declaration of the list
    list_with_files = []
    # for each key, identify it as a file or a folder
    # in the case of a folder, the files will be recursively gathered
    for key in paths:
        path = key.strip().lstrip("/")
        s3_files, total = list_s3_files_obj(s3_client, bucket, path, logger)
        if total == 0:
            logger.warning("No key {} found.".format(path))
            continue
        logger.debug("total: {} | s3_files = {}".format(total, s3_files))
        basename_part = get_basename(path)

        # check if it's a file or a dir
        if len(s3_files) == 1 and path == s3_files[0]:
            # the current key is a file, append it to the list
            list_with_files.append(("", s3_files[0]))
            logger.debug("ONE/ list_with_files = {}".format(list_with_files))
        else:
            # the current key is a folder, append all its files (reursively gathered) to the list
            for s3_file in s3_files:
                split = s3_file.split("/")
                split_idx = split.index(basename_part)
                list_with_files.append((os.path.join(*split[split_idx:-1]), s3_file.strip("/")))

    return list_with_files


# creates the list with local files to be uploaded to the bucket
# the list will contain pairs (s3_path, absolute_local_file_path)
# if the local file doesn't exist, the pair will be (None, requested_file_to_upload)
def files_to_be_uploaded(paths, logger):
    """Docstring to be added."""
    if logger is None:
        print("files_to_be_uploaded func: No logger object provided")
        return False

    list_with_files = []
    for local in paths:
        path = local.strip()
        # check if it is a file
        logger.debug("path = {}".format(path))
        if os.path.isfile(path):
            logger.debug("Add {} ".format(path))
            list_with_files.append(("", path))

        elif os.path.isdir(path):
            for root, dir_names, filenames in os.walk(path):
                for file in filenames:
                    full_file_path = os.path.join(root, file.strip("/"))
                    logger.debug("full_file_path = {} | dir_names = {}".format(full_file_path, dir_names))
                    if not os.path.isfile(full_file_path):
                        continue
                    logger.debug(
                        "get_basename(path) = {} | root = {} | replace = {}".format(
                            get_basename(path),
                            root,
                            root.replace(path, ""),
                        ),
                    )

                    keep_path = os.path.join(get_basename(path), root.replace(path, "").strip("/")).strip("/")
                    logger.debug("path = {} | keep_path = {} | root = {}".format(path, keep_path, root))

                    logger.debug("Add: {} | {}".format(keep_path, full_file_path))
                    list_with_files.append((keep_path, full_file_path))
        else:
            logger.warning("The path {} is not a directory nor a file, it will not be uploaded".format(path))

    return list_with_files


# get the content of a s3 directory
def list_s3_files_obj(s3_client, bucket, prefix, logger, max_timestamp=None, pattern=None):  # noqa
    """Docstring to be added."""
    if s3_client is None:
        sys.exit(-1)
    s3_files = []
    total = 0
    logger.warning("prefix = {}".format(prefix))
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
        for page in pages:
            for item in page.get("Contents", ()):
                if item is not None:
                    total += 1
                    if max_timestamp is not None:
                        if item["LastModified"] < max_timestamp:
                            # (s3_files[cnt])["Objects"].append(dict(Key=item["Key"]))
                            s3_files.append(item["Key"])
                            # logger.debug("{}".format(item["LastModified"]))
                    elif pattern is not None:
                        if pattern in item["Key"]:
                            # (s3_files[cnt])["Objects"].append(dict(Key=item["Key"]))
                            # logger.debug("found pattern {} in {} ".format(pattern, item["Key"]))
                            s3_files.append(item["Key"])
                    else:
                        # (s3_files[cnt])["Objects"].append(dict(Key=item["Key"]))
                        s3_files.append(item["Key"])
    except botocore.exceptions.ClientError as error:
        logger.error("Listing files from s3://{}/{} failed (client error):{}".format(bucket, prefix, error))
    except TypeError as typeErr:
        logger.error("Listing files from s3://{}/{} failed (type error):{}".format(bucket, prefix, typeErr))
    except KeyError as keyErr:
        logger.error("Listing files from s3://{}/{} failed (key error):{}".format(bucket, prefix, keyErr))

    return s3_files, total


def get_s3_data(s3_url):
    """Docstring to be added."""
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


def check_bucket_access(s3_client, bucket, logger):
    """Docstring to be added."""
    if s3_client is None or logger is None:
        raise
    try:
        s3_client.head_bucket(Bucket=bucket)
    except botocore.client.ClientError as error:
        # check that it was a 404 vs 403 errors
        # If it was a 404 error, then the bucket does not exist.
        error_code = int(error.response["Error"]["Code"])
        if error_code == S3_ERR_FORBIDDEN_ACCESS:
            logger.error("{} is a private bucket. Forbidden access!".format(bucket))
        elif error_code == S3_ERR_NOT_FOUND:
            logger.error("{} bucket does not exist!".format(bucket))
        return False

    return True
