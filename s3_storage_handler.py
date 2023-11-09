import ntpath
import os
import sys
import time
import traceback
from datetime import datetime
from threading import Lock

import boto3
import botocore
from prefect import get_run_logger, task

# seconds
DWN_S3FILE_RETRY_TIMEOUT = 6
DWN_S3FILE_RETRIES = 20
UP_S3FILE_RETRY_TIMEOUT = 6
UP_S3FILE_RETRIES = 20
global aws_terminating_node_notice
aws_terminating_node_notice = False
SET_PREFECT_LOGGING_LEVEL = "DEBUG"

s3_client_mutex = Lock()


# get the s3 handler
def get_s3_client():
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


# Prefect task to download a list of files from the s3 storage
# collection_files: list of files to be downloaded
#                   the list is formed from pair objects with the following
#                   syntax: (local_path_to_be_added_to_the_local_prefix, s3_key)
# bucket: name of the bucket
# local_prefix: local path where all the downloaded files will be saved
# idx: index of the task, should be unique
# overwrite: overwrites local files if they already exist. default True
# max_retries: maximum number of retries in case of a failed download
# returns: list with the s3 keys that coudn't be downloaded
@task
def prefect_download_file_from_s3(
    collection_files,
    bucket,
    local_prefix,
    idx,
    overwrite=True,
    max_retries=DWN_S3FILE_RETRIES,
):
    logger = get_run_logger()
    logger.setLevel(SET_PREFECT_LOGGING_LEVEL)
    failed_dwn_files = []

    s3_client = None
    for collection_file in collection_files:
        # get the s3 client
        if s3_client is None:
            s3_client = get_s3_client()
        if s3_client is None:
            logger.error("Could not get the s3 handler. Exiting....")
            sys.exit(-1)
        keep_trying = max_retries
        local_path = os.path.join(local_prefix, collection_file[0])
        s3_file = collection_file[1]
        # for each file to download, create the local dir (if it does not exist)
        os.makedirs(local_path, exist_ok=True)
        # create the path for local file
        local_file = os.path.join(local_path, os.path.basename(s3_file))
        cnt = 0
        if os.path.isfile(local_file):
            if overwrite:  # The file already exists, so delete it first
                logger.info(
                    "Downloading task {}: File {} already exists. Deleting it before downloading".format(
                        idx,
                        get_filename_only(local_file),
                    ),
                )
                os.remove(local_file)
            else:
                logger.info(
                    "Downloading task {}: File {} already exists. Skipping it".format(
                        idx,
                        get_filename_only(local_file),
                    ),
                )
                cnt += 1
                continue
        # download the files while no external termination notice is received
        while not aws_terminating_node_notice:
            try:
                dwn_start = datetime.now()
                logger.debug("Downloading task {}: s3://{}/{} downloading started ".format(idx, bucket, s3_file))
                s3_client.download_file(bucket, s3_file, local_file)
                logger.debug(
                    "Downloading task {}: s3://{}/{} downloaded to {} in {} ms".format(
                        idx,
                        bucket,
                        s3_file,
                        local_file,
                        datetime.now() - dwn_start,
                    ),
                )
                # for debug means
                cnt += 1
                if cnt % 10 == 0:
                    logger.debug(
                        "Downloading task {}: Files downloaded: {} from a total of {}".format(
                            idx,
                            cnt,
                            len(collection_files),
                        ),
                    )

                break
            except Exception as error:
                keep_trying -= 1
                if keep_trying == 0:
                    logger.error(
                        "Downloading task {}: Could not download the file {}. The download was \
retried for {} times. Last error: {}. Aborting".format(
                            idx,
                            s3_file,
                            max_retries,
                            error,
                        ),
                    )
                    failed_dwn_files.append(s3_file)
                    break
                logger.error(
                    "Downloading task {}: Error when downloading the file {}. \
Exception: {}. Retrying in {} seconds for {} more times".format(
                        idx,
                        s3_file,
                        error,
                        DWN_S3FILE_RETRY_TIMEOUT,
                        keep_trying,
                    ),
                )
                s3_client.close()
                s3_client = None
                time_cnt = 0
                while time_cnt < DWN_S3FILE_RETRY_TIMEOUT and not aws_terminating_node_notice:
                    time.sleep(0.2)
                    time_cnt += 0.2

    if aws_terminating_node_notice:
        print("SIGTERM received, everything has to be shutdown !")

    return failed_dwn_files


@task
def prefect_upload_file_to_s3(collection_files, bucket, s3_path, idx, max_retries=UP_S3FILE_RETRIES):
    logger = get_run_logger()
    logger.setLevel(SET_PREFECT_LOGGING_LEVEL)
    failed_up_files = []

    s3_client = None
    for collection_file in collection_files:
        # get the s3 client
        if s3_client is None:
            s3_client = get_s3_client()
        if s3_client is None:
            logger.error("Could not get the s3 handler. Exiting....")
            sys.exit(-1)
        keep_trying = max_retries
        file_to_be_uploaded = collection_file[1]
        # create the s3 key
        s3_obj = os.path.join(s3_path, collection_file[0], os.path.basename(file_to_be_uploaded))
        while not aws_terminating_node_notice:
            try:
                logger.info(
                    "Uploading task {}: copy file {} to s3://{}/{}".format(idx, file_to_be_uploaded, bucket, s3_obj),
                )
                s3_client.upload_file(file_to_be_uploaded, bucket, s3_obj)
                break
            except Exception as error:
                keep_trying -= 1
                if keep_trying == 0:
                    logger.error(
                        "Uploading task {}: Could not upload the file {} to s3://{}/{}. The upload was \
retried for {} times. Error: {}. Aborting".format(
                            idx,
                            file_to_be_uploaded,
                            bucket,
                            s3_obj,
                            max_retries,
                            error,
                        ),
                    )
                    failed_up_files.append(file_to_be_uploaded)
                    break
                logger.error(
                    "Uploading task {}: Error when uploading the file {}. \
Exception: {}. Retrying in {} seconds for {} more times".format(
                        idx,
                        file_to_be_uploaded,
                        error,
                        UP_S3FILE_RETRY_TIMEOUT,
                        keep_trying,
                    ),
                )
                s3_client.close()
                s3_client = None
                time_cnt = 0
                while time_cnt < UP_S3FILE_RETRY_TIMEOUT and not aws_terminating_node_notice:
                    time.sleep(0.2)
                    time_cnt += 0.2
                continue

    if aws_terminating_node_notice:
        print("SIGTERM received, everything has to be shutdown !")

    return failed_up_files


# delete a file from s3 by using the s3 handler
def delete_file_from_s3(s3_client, bucket, s3_obj):
    if s3_client is None or s3_obj is None or bucket is None or s3_obj is None:
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
    try:
        with open(secret_file, "r") as aws_credentials_file:
            lines = aws_credentials_file.readlines()
            for line in lines:
                if secrets["accesskey"] is not None and secrets["secretkey"] is not None:
                    break

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


def get_filename_only(path_to_file):
    path, filename = ntpath.split(path_to_file)
    return filename or ntpath.basename(path)


def files_to_be_downloaded(bucket, files_to_dwn, local_path, logger):
    s3_client = get_s3_client()
    if s3_client is None:
        logger.error("Could not get the s3 handler. Exiting....")
        sys.exit(-1)
    list_with_files = []
    with open(files_to_dwn, "r") as files:
        paths = files.readlines()
        logger.debug("paths = {}".format(paths))
        for path in paths:
            path = path.strip()
            # list_with_files = list_with_files + get_s3_files(s3_client, bucket, path, logger)
            s3_files, total = list_s3_files_obj(s3_client, bucket, path, logger)
            logger.debug("total: {} | s3_files = {}".format(total, s3_files))
            # check if it's a file only
            basename_part = os.path.basename(path)
            logger.debug("basename_part = {} |  {}".format(basename_part, s3_files[0]["Objects"][0]["Key"]))
            if len(s3_files[0]["Objects"]) == 1 and path == s3_files[0]["Objects"][0]["Key"]:
                list_with_files.append(("", s3_files[0]["Objects"][0]["Key"]))
                logger.debug("ONE/ list_with_files = {}".format(list_with_files))
            else:
                for idx in s3_files[0]["Objects"]:
                    logger.debug("IDX = {}".format(idx))
                    split = idx["Key"].split("/")
                    split_idx = split.index(basename_part)
                    logger.debug("split_idx = {}".format(split_idx))
                    logger.debug("split[split_idx:-1] = {}".format(split[split_idx:-1]))
                    list_with_files.append((os.path.join(*split[split_idx:-1]), idx["Key"]))
                    logger.debug("IDX/ list_with_files = {}".format(list_with_files))

    return list_with_files


def files_to_be_uploaded(s3_path, files_to_upload, logger):
    list_with_files = []
    with open(files_to_upload, "r") as files:
        paths = files.readlines()
        logger.debug("paths = {}".format(paths))
        for path in paths:
            path = path.strip()
            # check if it is a file
            if os.path.isfile(path):
                logger.debug("Add {} ".format(path))
                list_with_files.append(("", path))

            elif os.path.isdir(path):
                for root, dir_names, filenames in os.walk(path):
                    for file in filenames:
                        full_file_path = os.path.join(root, file)
                        if not os.path.isfile(full_file_path):
                            continue
                        logger.debug("path = {} | root = {}".format(path, root))
                        keep_path = root.replace(path, "")
                        if keep_path.startswith("/"):
                            if len(keep_path) == 1:
                                keep_path = ""
                            else:
                                keep_path = keep_path[1:]
                        list_with_files.append((keep_path, full_file_path))
            else:
                logger.warning("The path {} is not a directory nor a file, it will not be uploaded".format(path))

    return list_with_files


# get the content of a s3 directory
def list_s3_files(s3_client, bucket, prefix, logger, with_path=True):
    s3_files = []
    try:
        list_objects_paginator = s3_client.get_paginator("list_objects")
        for result in list_objects_paginator.paginate(Bucket=bucket, Prefix=prefix):
            for s3_file in result["Contents"]:
                # don't count the directories, files only
                if not s3_file["Key"].endswith("/"):
                    if with_path:
                        s3_files.append(s3_file["Key"])
                    else:
                        # parts = s3_file['Key'].split("/")
                        s3_files.append(s3_file["Key"].split("/")[-1])
                else:
                    logger.info("List S3 files: Skip {} because it seems to be a directory".format(s3_file["Key"]))
        return s3_files
    except TypeError:
        logger.error("Listing files from s3://{}/{} failed, error {}".format(bucket, prefix, TypeError))
        return s3_files
    except KeyError:
        logger.error("Listing files from s3://{}/{} failed, error {}".format(bucket, prefix, KeyError))
        return s3_files


def list_s3_files_obj(s3_client, bucket_name, prefix, logger, max_timestamp=None, pattern=None):
    if s3_client is None:
        try:
            s3_client = get_s3_client()
        except Exception as e:
            print("get_s3_client exception :{}".format(e))
            logger.error("Could not obtain the handler for the s3 connection! {}".format(e))
            os._exit(-1)

    s3_files = dict(Objects=[])
    total = 0
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        s3_files = []
        for page in pages:
            # logger.debug("1")
            s3_files.append(dict(Objects=[]))
            cnt = len(s3_files) - 1
            # logger.debug("2")
            for item in page.get("Contents", ()):
                # logger.debug("3")
                if item is not None:
                    total += 1
                    if max_timestamp is not None:
                        if item["LastModified"] < max_timestamp:
                            (s3_files[cnt])["Objects"].append(dict(Key=item["Key"]))
                            # logger.debug("{}".format(item["LastModified"]))
                    elif pattern is not None:
                        if pattern in item["Key"]:
                            (s3_files[cnt])["Objects"].append(dict(Key=item["Key"]))
                            logger.debug("found pattern {} in {} ".format(pattern, item["Key"]))
                    else:
                        (s3_files[cnt])["Objects"].append(dict(Key=item["Key"]))
        return s3_files, total
    except TypeError as typeErr:
        print("Listing files from s3://{}/{} failed (type error):{}".format(bucket_name, prefix, typeErr))
        return s3_files, total
    except KeyError as keyErr:
        print("Listing files from s3://{}/{} failed (key error):{}".format(bucket_name, prefix, keyErr))
        return s3_files, total


def get_s3_data(s3_url):
    s3_data = s3_url.replace("s3://", "").split("/")
    bucket_name = ""
    start_idx = 0
    if s3_url.startswith("s3://"):
        bucket_name = s3_data[0]

        start_idx = 1
    prefix = ""
    if start_idx < len(s3_data):
        prefix = "/".join(s3_data[start_idx:-1])
    s3_file = s3_data[-1]
    return bucket_name, prefix, s3_file
