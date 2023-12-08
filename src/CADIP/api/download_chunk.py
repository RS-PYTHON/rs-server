"""Docstring will be here."""
import os
import random
import threading
from datetime import datetime
from threading import Event

from eodag import EODataAccessGateway, EOProduct
from fastapi import APIRouter

from src.s3_storage_handler.s3_storage_handler import prefect_put_files_to_s3

thread_started = Event()
router = APIRouter()


def update_db(id, status):
    """Docstring will be here."""
    print("Fake update of table dwn_status with : {} | {}".format(id, status))


def start_eodag_download(station, id, name, local, obs):  # noqa: D417
    """Initiate a download using the EODAG (Earth Observation Data Access Gateway) client.

    Parameters
    ----------
    - station (str): The identifier of the Earth Observation station.
    - id (str): The unique identifier associated with the data to be downloaded.
    - name (str): The name of the data product to be downloaded.
    - local (str): The local path where the downloaded data will be stored.
    - obs (str): Additional observation-related information.

    Returns
    -------
    None

    The function initiates the download process using EODAG, with a sleep of 10 seconds
    to ensure proper initialization. It then updates the database with the download progress,
    attempts to download the specified data using EODAG, and handles any exceptions that may occur.
    If the download is successful, the function prints the EODAG location and updates the
    database with the download success status.

    If an exception occurs during the download process, it is caught, and the function
    prints an error message, updates the database with the download failure status, and exits.
    """
    # init eodag object
    # time.sleep(1)
    init = datetime.now()
    dag_client = init_eodag(station)
    print("init_eodag time: {}".format(datetime.now() - init))
    if local is not None:
        # set the path where the file should be downloaded
        dag_client.update_providers_config(
            f"""
        {station}:
            download:
                outputs_prefix: '{local}'
        """
        )
    init = datetime.now()
    eop = init_eop(id, name, local)
    print("init_eop time: {}".format(datetime.now() - init))
    # insert into database the filename with status set to progress
    try:
        thread_started.set()
        print("set event !")
        init = datetime.now()
        random.randint(9, 20)
        dag_client.download(eop)
        print("download time: {}".format(datetime.now() - init))
    except Exception as e:
        print("Exception caught: {}".format(e))
        update_db(id, "failed")
        return
    print("Downloaded file: {}".format(eop.location))

    if obs is not None:
        filename = eop.location
        obs_array = obs.split("/")
        # TODO check the length
        prefect_put_files_to_s3([filename], obs_array[3], "/".join(obs_array[4:]))

        os.remove(filename)

    update_db(id, "succeeded")


@router.get("/cadip/{station}/cadu")
def download(station: str, id: str, name: str, local: str, obs: str):  # noqa: D417
    """Initiate an asynchronous download process using EODAG (Earth Observation Data Access Gateway).

    Parameters
    ----------
    - station (str): The identifier of the Earth Observation station.
    - id (str, optional): The unique identifier associated with the data to be downloaded.
    - name (str, optional): The name of the data product to be downloaded.
    - local (str, optional): The local path where the downloaded data will be stored.
    - obs (str, optional): Additional observation-related information.

    Returns
    -------
    dict: A dictionary indicating that the download process has been started.

    The function initiates an asynchronous download process by starting a new thread to execute
    the 'start_eodag_download' function. It prints information before and after starting the thread,
    checks the start of the thread, and updates the database with the download start status.

    Note: The actual download progress can be monitored separately, and the function returns a
    dictionary with the key "started" set to "true" to indicate that the download process has begun.
    """
    # start a thread ->
    print("Before starting thread, local = {} | ".format(locals()))
    thread = threading.Thread(
        target=start_eodag_download,
        args=(
            station,
            id,
            name,
            local,
            obs,
        ),
    )
    thread.start()
    # check the start of the thread
    if not thread_started.wait(timeout=2):
        print("Download thread did not start !")
        # update the status in database
        update_db(id, "failed")
        return {"started": "false"}

    # update the status in database
    update_db(id, "progress")
    return {"started": "true"}


def init_eodag(station):
    """Docstring will be here."""
    config_file_path = "CADIP/library/cadip_ws_config.yaml"
    eodag = EODataAccessGateway(config_file_path)
    eodag.set_preferred_provider(station)
    return eodag


def init_eop(file_id: str, name: str, path: str):
    """Docstring will be here."""
    properties = {
        "title": name,
        "id": file_id,
        "geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))",
        "downloadLink": f"http://127.0.0.1:5000/Files({file_id})/$value",
        "outputs_prefix": path,
    }
    product = EOProduct("CADIP", properties)
    # product.register_downloader()
    return product
