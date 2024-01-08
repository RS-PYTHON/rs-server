"""Docstring will be here."""
import asyncio
import os
import os.path as osp
import threading
from datetime import datetime
from pathlib import Path
from threading import Event

from eodag import EODataAccessGateway, EOProduct, setup_logging
from eodag.utils import uri_to_path
from fastapi import APIRouter

from rs_server.s3_storage_handler.s3_storage_handler import (
    PrefectPutFilesToS3Config,
    S3StorageHandler,
    prefect_put_files_to_s3,
)
from services.common.rs_server_common.data_retrieval.eodag_provider import (
    EodagConfiguration,
    EodagProvider,
)

DWN_THREAD_START_TIMEOUT = 1.8
thread_started = Event()
router = APIRouter()

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "CADIP" / "library"


def update_db(id, status):
    """Docstring will be here."""
    print(
        "%s : %s : %s: Fake update of table dwn_status with : %s | %s",
        os.getpid(),
        threading.get_ident(),
        datetime.now(),
        id,
        status,
    )


def start_eodag_download(station, id, name, local, obs: str = "", secrets={}):
    """Download a chunk file.

    Initiates a download using EODAG (Earth Observation Data Access Gateway) for a specific
    satellite station with the given parameters.

    Parameters
    ----------
    station : str
        The name of the satellite station.
    id : str
        Identifier for the download operation.
    name : str
        Name associated with the download operation.
    local : str
        The local path where the file should be downloaded. If None, the default
        path is used.
    obs : str
        The observation details, including the destination path for uploading the file
        after download. If None, the file is not uploaded.

    Returns
    -------
    None

    Notes
    -----
    - The function initializes EODAG, sets the download path if provided, initializes an
      Earth Observation Package (EOP), and then downloads the data using EODAG.
    - After a successful download, it updates the database with a "succeeded" status.
    - If an observation path is provided, it uploads the file to the specified destination
      and deletes the local file after uploading.

    Example
    -------
    >>> start_eodag_download("Sentinel-1", "12345", "Download_1", "/path/to/local", "s3://bucket/data")
    """
    # init eodag object
    try:
        print("%s : %s : %s: Thread started !", os.getpid(), threading.get_ident(), datetime.now())
        config_file_path = CONF_FOLDER / "cadip_ws_config.yaml"

        setup_logging(3, no_progress_bar=True)

        eodag_config = EodagConfiguration(station, Path(config_file_path))
        eodag_client = EodagProvider(eodag_config)

        thread_started.set()

        local_file = osp.join(local, name)
        init = datetime.now()
        eodag_client.download(id, Path(local_file))
        end = datetime.now()
        print(
            "%s : %s : %s: Downloaded file: %s   in %s",
            os.getpid(),
            threading.get_ident(),
            end,
            name,
            end - init,
        )
    except Exception as e:
        print("%s : %s : %s: Exception caught: %s", os.getpid(), threading.get_ident(), datetime.now(), e)
        update_db(id, "failed")
        return

    if obs is not None and len(obs) > 0:
        try:
            
            s3_handler = S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], "sbg")

            obs_array = obs.split("/")

            # TODO check the length
            s3_config = PrefectPutFilesToS3Config(s3_handler, [local_file], obs_array[2], "/".join(obs_array[3:]), 0)
            asyncio.run(prefect_put_files_to_s3.fn(s3_config))
        except RuntimeError:
            print("Could not connect to the s3 storage")
        finally:
            os.remove(local_file)

    update_db(id, "succeeded")


@router.get("/cadip/{station}/cadu")
def download(station: str, id: str, name: str, local: str = "", obs: str = ""):
    """Initiate an asynchronous download process using EODAG (Earth Observation Data Access Gateway).

    Parameters
    ----------
    station : str
        Identifier of the Earth Observation station.
    id : str, optional
        Unique identifier associated with the data to be downloaded.
    name : str, optional
        Name of the data product to be downloaded.
    local : str, optional
        Local path where the downloaded data will be stored.
    obs : str, optional
        Additional observation-related information.

    Returns
    -------
    dict
        A dictionary indicating that the download process has been started.

    Notes
    -----
    The function initiates an asynchronous download process by starting a new thread to execute
    the 'start_eodag_download' function. It prints information before and after starting the thread,
    checks the start of the thread, and updates the database with the download start status.

    The actual download progress can be monitored separately, and the function returns a
    dictionary with the key "started" set to "true" to indicate that the download process has begun.

    Example
    -------
    >>> result = download("Sentinel-1", id="12345", name="Download_1", local="/path/to/local", obs="s3://bucket/data")
    >>> print(result)
    {'started': True}
    """
    """
    start_eodag_download(station,
            id,
            name,
            local,
            obs)
    update_db(id, "succeeded")
    return {"downloaded": "true"}
    """
    # start a thread to run the action in background

    print(
        "%s : %s : %s: MAIN THREAD: Starting thread, local = %s",
        os.getpid(),
        threading.get_ident(),
        datetime.now(),
        locals(),
    )
    # TODO: the secrets should be set through env vars
    secrets = {
        "s3endpoint": None,
        "accesskey": None,
        "secretkey": None,
    }
    S3StorageHandler.get_secrets(secrets, "/home/" + os.environ["USER"] + "/.s3cfg")
    thread = threading.Thread(
        target=start_eodag_download,
        args=(
            station,
            id,
            name,
            local,
            obs,
            secrets,
        ),
    )
    thread.start()
    thread.join()
    """
    # check the start of the thread
    if not thread_started.wait(timeout=DWN_THREAD_START_TIMEOUT):
        print("Download thread did not start !")
        # update the status in database
        update_db(id, "failed")
        return {"started": "false"}
    """
    # update the status in database
    update_db(id, "progress")

    return {"started": "true"}
