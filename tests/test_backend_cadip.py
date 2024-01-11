"""Docstring will be here."""
import argparse
import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from itertools import islice

import requests
from prefect import exceptions, flow, get_run_logger, task
from prefect_dask.task_runners import DaskTaskRunner

SET_PREFECT_LOGGING_LEVEL = "DEBUG"
global gen_logger


def dictionary_files(data, size_of_chunk=10):
    it = iter(data)
    for i in range(0, len(data), size_of_chunk):
        yield {k: data[k] for k in islice(it, size_of_chunk)}


@task
async def start_download(station, files_info, local_path, obs, idx):
    # start command (curl)
    try:
        logger = get_run_logger()
        logger.setLevel(SET_PREFECT_LOGGING_LEVEL)
    except exceptions.MissingContextError:
        logger = gen_logger
        logger.info("Could not get the prefect logger due to missing context")

    if obs is None:
        obs = ""

    logger.info("Task {} start time: {}".format(idx, datetime.now()))
    for cadu_id, filename in files_info.items():
        if len(obs) == 0:
            payload = {"cadu_id": cadu_id, "name": filename, "local": local_path}
        else:
            payload = {"cadu_id": cadu_id, "name": filename, "obs": obs}
        logger.info("Task {}: payload: {}".format(idx, payload))
        response = requests.get("http://127.0.0.1:8000/cadip/{}/cadu".format(station), params=payload)
        logger.info("Task {}: Url: {}".format(idx, response.url))
        logger.info("Task {}: Response got: {}".format(idx, response.json()))
        # TODO ! Get download status from the server !!
        #
        payload = {"cadu_id": cadu_id, "name": filename}
        response = ""
        timeout = 10
        while response != "done" and timeout > 0:
            response = requests.get(
                "http://127.0.0.1:8000/cadip/{}/cadu/status".format(station),
                params=payload,
            ).text.strip('"')
            time.sleep(1)
            timeout -= 1
        logger.info("Get status is: %s", response)
        if timeout <= 0:
            logger.error(
                "Timeout for receiving the downloaded status from server passed. \
The file %s wasn't downloaded properly",
                filename,
            )
        """
        # tests: for parallel search
        payload = {"start_date": "2023-01-01T12:00:00.000Z", "stop_date": "2033-02-20T12:00:00.000Z"}
        init = datetime.now()
        response = requests.get("http://127.0.0.1:8000/cadip/{}/cadu/list".format(args.station), params = payload)
        logger.info("Task {}: Service completed in: {}".format(idx, datetime.now() - init))
        init_1 = datetime.now()
        data = eval(response.content.decode())
        logger.info("Task {}: Decode in {} | Response: {}".format(idx, datetime.now() - init_1, data))
        """


def get_ceil(a, b):
    return -(a // -b)


@flow(task_runner=DaskTaskRunner())
def download_flow(station, files, max_runners, location, obs=None):
    """Docstring to be added."""
    # get the Prefect logger
    logger = get_run_logger()
    logger.setLevel(SET_PREFECT_LOGGING_LEVEL)
    logger.info("List of files found in STATION = {}".format(files))
    # nb_of_tasks = min(max_runners, len(files))
    # force the number of tasks to 1 due to the inability of eodag to run in parallel on the same system
    nb_of_tasks = 1
    list_per_task = [None] * nb_of_tasks
    current_idx = 0
    for key, value in files.items():
        if list_per_task[current_idx] is None:
            list_per_task[current_idx] = {}
        list_per_task[current_idx][key] = value
        if current_idx == (nb_of_tasks - 1):
            current_idx = 0
        else:
            current_idx += 1
    idx = 0
    for dictionay_it in list_per_task:
        # logger.debug("dictionay_it = {}| type = {}".format(dictionay_it, type(dictionay_it)))
        start_download.submit(station, dictionay_it, location, obs, idx)
        idx += 1


if __name__ == "__main__":
    """This is a demo which integrates the search and download from a CADIP server. It also checks the download status"""
    log_folder = "./demo/"
    os.makedirs(log_folder, exist_ok=True)
    log_formatter = logging.Formatter("[%(asctime)-20s] [%(name)-10s] [%(levelname)-6s] %(message)s")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(log_formatter)
    log_filename = log_folder + "s3_handler_" + time.strftime("%Y%m%d_%H%M%S") + ".log"
    file_handler = logging.FileHandler(log_filename)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(log_formatter)
    gen_logger = logging.getLogger("test_backend")
    gen_logger.setLevel(logging.DEBUG)
    gen_logger.handlers = []
    gen_logger.propagate = False
    gen_logger.addHandler(console_handler)
    gen_logger.addHandler(file_handler)
    logger = gen_logger

    parser = argparse.ArgumentParser(
        description="Starts the demo for sprint 1 phase",
    )
    parser.add_argument("-s", "--station", type=str, required=True, help="Station name")

    parser.add_argument("-b", "--start-date", type=str, required=True, help="Start date used for time interval search")

    parser.add_argument("-e", "--stop-date", type=str, required=True, help="Stop date used for time interval search")

    parser.add_argument(
        "-t",
        "--max-tasks",
        type=int,
        required=False,
        help="Maximum number of prefect tasks. Default 1 (flow will not be started)",
        default=1,
    )

    parser.add_argument(
        "-l",
        "--location",
        type=str,
        required=False,
        help="Location where the files are saved",
        default="/tmp/cadu",
    )

    parser.add_argument(
        "-o",
        "--s3-storage",
        type=str,
        required=False,
        help="Location on the bucket where the files will be pushed through s3 protocol",
    )

    args = parser.parse_args()
    # http://127.0.0.1:8000/cadip/CADIP/cadu/list?start_date="1999-01-01T12:00:00.000Z"&stop_date="2033-02-20T12:00:00.000Z"
    # payload = {"start_date": "2023-01-01T12:00:00.000Z", "stop_date": "2033-02-20T12:00:00.000Z"}
    payload = {"start_date": args.start_date, "stop_date": args.stop_date}
    response = requests.get("http://127.0.0.1:8000/cadip/{}/cadu/list".format(args.station), params=payload)
    data = eval(response.content.decode())
    logger.debug("data = {}".format(data))
    files = {}
    for file_info in data["{}".format(args.station)]:
        files[file_info[0]] = file_info[1]
    # logger.debug(locals())

    if args.max_tasks <= 1:
        asyncio.run(start_download.fn(args.station, files, args.location, args.s3_storage, 0))
        logger.debug("start_download finished")
    else:
        dwn_flow = download_flow(args.station, files, args.location, args.s3_storage)

    # module_classification_processor(bucket, key, "aux_data", args.max_tasks)

    logger.info("EXIT !")
