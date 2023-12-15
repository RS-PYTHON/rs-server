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

from rs_server.s3_storage_handler.s3_storage_handler import files_to_be_uploaded, get_secrets, prefect_put_files_to_s3

DWN_THREAD_START_TIMEOUT = 1.8
thread_started = Event()
router = APIRouter()

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "CADIP" / "library"


def update_db(id, status):
    """Docstring will be here."""
    print(
        "{} : {} : {}: Fake update of table dwn_status with : {} | {}".format(
            os.getpid(), threading.get_ident(), datetime.now(), id, status
        )
    )


def start_eodag_download(station, id, name, local, obs):
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
        init = datetime.now()
        print("{os.getpid()} : {threading.get_ident()} : {init}: Thread started !")
        setup_logging(3, no_progress_bar=True)

        dag_client = init_eodag(station)
        end = datetime.now()
        print("{} : {} : {}: init_eodag time {}".format(os.getpid(), threading.get_ident(), end, end - init))

        init = datetime.now()
        eop = init_eop(id, name)
        end = datetime.now()
        print("{} : {} : {}: init_eop time: {}".format(os.getpid(), threading.get_ident(), end, end - init))

        # insert into database the filename with status set to progress

        thread_started.set()
        print("{} : {} : {}: set event !".format(os.getpid(), threading.get_ident(), datetime.now()))
        init = datetime.now()
        # time.sleep(random.randint(9, 20))
        if len(local) == 0:
            local = "/tmp"
        dag_client.download(eop, outputs_prefix=local)
        end = datetime.now()
        # print("{} : {} : {}: download time: {}".format(os.getpid(), threading.get_ident(), end, ))
        print(
            "{} : {} : {}: Downloaded file: {}   in {}".format(
                os.getpid(), threading.get_ident(), end, eop.location, end - init
            )
        )
    except Exception as e:
        print("{} : {} : {}: Exception caught: {}".format(os.getpid(), threading.get_ident(), datetime.now(), e))
        update_db(id, "failed")
        return

    if obs is not None and len(obs) > 0:
        # TODO: the secrets should be set through env vars
        secrets = {
            "s3endpoint": None,
            "accesskey": None,
            "secretkey": None,
        }
        get_secrets(secrets, "/home/" + os.environ["USER"] + "/.s3cfg")
        print(f"secrets = {secrets}")
        os.environ["S3_ENDPOINT"] = secrets["s3endpoint"] if secrets["s3endpoint"] is not None else ""
        os.environ["S3_ACCESS_KEY_ID"] = secrets["accesskey"] if secrets["accesskey"] is not None else ""
        os.environ["S3_SECRET_ACCESS_KEY"] = secrets["secretkey"] if secrets["secretkey"] is not None else ""
        os.environ["S3_REGION"] = "sbg"
        filename = uri_to_path(eop.location)
        obs_array = obs.split("/")
        print(
            "filename = {} | obs_array = {} | join = {} | filename {}".format(
                filename, obs_array, "/".join(obs_array[2:]), "/".join(obs_array[2:]) + name
            )
        )

        # TODO check the length
        collection = files_to_be_uploaded([filename])
        asyncio.run(prefect_put_files_to_s3.fn(collection, obs_array[2], "/".join(obs_array[3:]), 0))

        os.remove(filename)

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
        "{} : {} : {}: MAIN THREAD: Starting thread, local = {}".format(
            os.getpid(), threading.get_ident(), datetime.now(), locals()
        )
    )
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
    if not thread_started.wait(timeout=DWN_THREAD_START_TIMEOUT):
        print("Download thread did not start !")
        # update the status in database
        update_db(id, "failed")
        return {"started": "false"}

    # update the status in database
    update_db(id, "progress")

    return {"started": "true"}


def init_eodag(station):
    """Initialize eodag.

    Initialize an instance of the Earth Observation Data Access Gateway (EODAG) for a specified
    satellite station.

    Parameters
    ----------
    station : str
        Identifier for the CADU station.

    Returns
    -------
    EODataAccessGateway
        An instance of the EODAG configured for the specified station.

    Example:
        eodag_instance = init_eodag("Sentinel-1")
    """
    config_file_path = CONF_FOLDER / "cadip_ws_config.yaml"
    eodag = EODataAccessGateway(config_file_path)
    eodag.set_preferred_provider(station)
    return eodag


def init_eop(file_id: str, name: str) -> EOProduct:
    """Initialize EOP.

    Initializes an Earth Observation Package (EOP) with the specified parameters.

    Parameters
    ----------
    file_id : str
        Identifier for the Earth Observation Product (EOP).
    name : str
        Name associated with the EOP.
    path : str
        The local path where the file associated with the EOP should be stored.

    Returns
    -------
    EOProduct
        An instance of the Earth Observation Product (EOP) initialized
        with the provided parameters.

    Example
    -------
    >>> eop_instance = init_eop("12345", "Sentinel-1_Image", "/path/to/local")
    """
    properties = {
        "title": name,
        "id": file_id,
        "geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))",
        "downloadLink": f"http://127.0.0.1:5000/Files({file_id})/$value",
    }
    product = EOProduct("CADIP", properties)
    # product.register_downloader()
    return product
