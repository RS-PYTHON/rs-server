"""Docstring will be here."""
import asyncio
import os
import os.path as osp
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Event

from eodag import EODataAccessGateway, EOProduct, setup_logging
from eodag.utils import uri_to_path
from fastapi import APIRouter, Depends

from rs_server.CADIP.models.cadu_download_status import (
    CaduDownloadStatus,
    EDownloadStatus,
)
from rs_server.db.database import get_db
from rs_server.s3_storage_handler.s3_storage_handler import (
    PrefectPutFilesToS3Config,
    S3StorageHandler,
    prefect_put_files_to_s3,
)

DWN_THREAD_START_TIMEOUT = 1.8
thread_started = Event()
router = APIRouter(tags=["Cadu products"])

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "CADIP" / "library"


def update_db(db, product, status, status_fail_message=None):
    """Docstring will be here."""
    print(
        "{} : {} : {}: Update of table dwn_status with : {} | {}".format(
            os.getpid(),
            threading.get_ident(),
            datetime.now(),
            product.cadu_id,
            status,
        ),
    )

    product.status = status
    product.status_fail_message = status_fail_message
    db.commit()  # TODO: attempt 3 times and stop


def start_eodag_download(station, product_id, local, obs):
    """Download a chunk file.

    Initiates a download using EODAG (Earth Observation Data Access Gateway) for a specific
    satellite station with the given parameters.

    Parameters
    ----------
    station : str
        The name of the satellite station.
    product_id: CaduDownloadStatus
        Database entry ID for the product download status
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

    # Get a database connection in this thread, because the connection from the
    # main thread does not seem to be working in sub-thread (was it closed ?)
    with contextmanager(get_db)() as db:
        # Get the product download status from database. It was created before running this thread.
        # TODO: should we recreate it if it was deleted for any reason ?
        product = db.query(CaduDownloadStatus).where(CaduDownloadStatus.id == product_id).one()

        # init eodag object
        try:
            init = datetime.now()
            print("{os.getpid()} : {threading.get_ident()} : {init}: Thread started !")
            setup_logging(3, no_progress_bar=True)

            dag_client = init_eodag(station)
            end = datetime.now()
            print("{} : {} : {}: init_eodag time {}".format(os.getpid(), threading.get_ident(), end, end - init))

            init = datetime.now()
            eop = init_eop(product)
            end = datetime.now()
            print("{} : {} : {}: init_eop time: {}".format(os.getpid(), threading.get_ident(), end, end - init))

            # insert into database the filename with status set to "downloading"

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
                    os.getpid(),
                    threading.get_ident(),
                    end,
                    eop.location,
                    end - init,
                ),
            )
        except Exception as e:
            print("{} : {} : {}: Exception caught: {}".format(os.getpid(), threading.get_ident(), datetime.now(), e))
            update_db(db, product, EDownloadStatus.FAILED, repr(e))
            return

        if obs is not None and len(obs) > 0:
            # TODO: the secrets should be set through env vars
            secrets = {
                "s3endpoint": None,
                "accesskey": None,
                "secretkey": None,
            }
            S3StorageHandler.get_secrets(secrets, "/home/" + os.environ["USER"] + "/.s3cfg")
            print(f"secrets = {secrets}")
            s3_handler = S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], "sbg")

            filename = uri_to_path(eop.location)
            obs_array = obs.split("/")
            print(
                "filename = {} | obs_array = {} | join = {} | filename {}".format(
                    filename,
                    obs_array,
                    "/".join(obs_array[2:]),
                    "/".join(obs_array[2:]) + product.name,
                ),
            )

            # TODO check the length
            s3_config = PrefectPutFilesToS3Config(s3_handler, [filename], obs_array[2], "/".join(obs_array[3:]), 0)
            asyncio.run(prefect_put_files_to_s3.fn(s3_config))

            os.remove(filename)

        update_db(db, product, EDownloadStatus.DONE)


@router.get("/cadip/{station}/cadu")
def download(station: str, cadu_id: str, name: str, local: str = "", obs: str = "", db=Depends(get_db)):
    """Initiate an asynchronous download process using EODAG (Earth Observation Data Access Gateway).

    Parameters
    ----------
    station : str
        Identifier of the Earth Observation station.
    cadu_id : str
        Unique ID of the Earth Observation Product (EOP) to be downloaded.
    name : str
        Name of the Earth Observation Product (EOP) to be downloaded.
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
    """

    # Does the product download status already exist in database ? Filter on the EOP ID.
    query = db.query(CaduDownloadStatus).where(CaduDownloadStatus.cadu_id == cadu_id)
    if query.count():
        # Get the existing product and overwrite the download status.
        # TODO: should we keep download history in a distinct table and init a new download entry ?
        product = query.one()
        update_db(db, product, EDownloadStatus.NOT_STARTED)

    # Else init a new entry from the input arguments
    else:
        product = CaduDownloadStatus(cadu_id=cadu_id, name=name, status=EDownloadStatus.NOT_STARTED)
        db.add(product)
        db.commit()

    # start a thread to run the action in background

    print(
        "{} : {} : {}: MAIN THREAD: Starting thread, local = {}".format(
            os.getpid(),
            threading.get_ident(),
            datetime.now(),
            locals(),
        ),
    )
    thread = threading.Thread(
        target=start_eodag_download,
        args=(
            station,
            product.id,
            local,
            obs,
        ),
    )
    thread.start()
    # check the start of the thread
    if not thread_started.wait(timeout=DWN_THREAD_START_TIMEOUT):
        print("Download thread did not start !")
        # update the status in database
        update_db(db, product, EDownloadStatus.FAILED, "Download thread did not start !")
        return {"started": "false"}

    # update the status in database
    update_db(db, product, EDownloadStatus.IN_PROGRESS)

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


def init_eop(product: CaduDownloadStatus) -> EOProduct:
    """Initialize EOP.

    Initializes an Earth Observation Package (EOP) with the specified parameters.

    Parameters
    ----------
    product: CaduDownloadStatus
        Database entry for the product download status
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
        "title": product.name,
        "id": product.cadu_id,
        "geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))",
        "downloadLink": f"http://127.0.0.1:5000/Files({product.cadu_id})/$value",
    }
    product = EOProduct("CADIP", properties)
    # product.register_downloader()
    return product
