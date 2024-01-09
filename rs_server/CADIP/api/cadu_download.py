"""Docstring will be here."""
import asyncio
import os
import os.path as osp
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Event

from eodag import setup_logging
from eodag.utils import uri_to_path
from fastapi import APIRouter, Depends

from rs_server.db.models.cadu_product_model import CaduProduct
from rs_server.db.models.download_status import DownloadStatus
from rs_server.db.session import get_db
from rs_server.s3_storage_handler.s3_storage_handler import (
    PrefectPutFilesToS3Config,
    S3StorageHandler,
    prefect_put_files_to_s3,
)
from services.cadip.rs_server_cadip.cadip_retriever import init_cadip_data_retriever
from services.common.rs_server_common.data_retrieval.eodag_provider import EodagProvider

DWN_THREAD_START_TIMEOUT = 1.8
thread_started = Event()
router = APIRouter()

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent.parent / "services" / "cadip" / "config"


def update_db(db, product, status, status_fail_message=None):
    """Update the database with the status of a product.

    This function performs a fake update of the 'dwn_status' table with the provided
    product status information. It updates the status, status_fail_message, and timestamps
    based on the specified status. If the status is 'IN_PROGRESS', it sets the downlink_start
    timestamp; if the status is 'DONE', it sets the downlink_stop timestamp.

    Args:
        db (Database): The database connection object.
        product (Product): The product to be updated in the database.
        status (DownloadStatus): The new status of the product.
        status_fail_message (str, optional): The failure message associated with the status.

    Returns:
        None

    Raises:
        None
    """

    product.status = status
    product.status_fail_message = status_fail_message
    if status == DownloadStatus.IN_PROGRESS:
        product.downlink_start = datetime.now()
    if status == DownloadStatus.DONE:
        product.downlink_stop = datetime.now()
    db.commit()


def start_eodag_download(station, db_id, file_id, name, local, obs: str = "", secrets={}):
    """Start an EODAG download process for a specified product.

    This function initiates a download process using EODAG to retrieve a product with the given
    parameters. It also updates the product's status in the database based on the download result.

    Args:
        station (str): The EODAG station identifier.
        db_id (int): The database identifier of the product.
        file_id (str): The file identifier of the product.
        name (str): The name of the product.
        local (str): The local path where the product will be downloaded.
        obs (str, optional): The observation identifier associated with the product.
        secrets (dict, optional): Dictionary containing access key, secret key, and S3 endpoint for authentication.

    Returns:
        None

    Raises:
        None
    """
    # Get a database connection in this thread, because the connection from the
    # main thread does not seem to be working in sub-thread (was it closed ?)
    status = DownloadStatus.FAILED
    with contextmanager(get_db)() as db:
        # Get the product download status from database. It was created before running this thread.
        # TODO: should we recreate it if it was deleted for any reason ?
        product = db.query(CaduProduct).where(CaduProduct.id == db_id).first()

        # init eodag object
        try:
            print("%s : %s : %s: Thread started !", os.getpid(), threading.get_ident(), datetime.now())
            # config_file_path = CONF_FOLDER / "cadip_ws_config.yaml"

            setup_logging(3, no_progress_bar=True)

            # eodag_provider = EodagProvider(Path(config_file_path), station)
            if len(local) == 0:
                local = "/tmp"

            data_retriever = init_cadip_data_retriever(EodagProvider, station, None, None, Path(local))

            thread_started.set()
            init = datetime.now()
            data_retriever.download(file_id, name)
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
            update_db(db, product, status)
            return

        if obs is not None and len(obs) > 0:
            try:
                s3_handler = S3StorageHandler(secrets["accesskey"], secrets["secretkey"], secrets["s3endpoint"], "sbg")
                obs_array = obs.split("/")
                # TODO check the length
                s3_config = PrefectPutFilesToS3Config(
                    s3_handler,
                    [str(data_retriever.filename)],
                    obs_array[2],
                    "/".join(obs_array[3:]),
                    0,
                )
                asyncio.run(prefect_put_files_to_s3.fn(s3_config))
                status = DownloadStatus.DONE
            except RuntimeError:
                print("Could not connect to the s3 storage")
            finally:
                os.remove(data_retriever.filename)

        update_db(db, product, status)


@router.get("/cadip/{station}/cadu")
def download(station: str, file_id: str, name: str, local: str = "", obs: str = "", db=Depends(get_db)):
    """Initiate an asynchronous download process for a CADU product using EODAG.

    This endpoint triggers the download of a CADU product identified by the given file_id,
    name, and observation identifier. It starts the download process in a separate thread
    using the start_eodag_download function and updates the product's status in the database.

    Args:
        station (str): The EODAG station identifier.
        file_id (str): The file identifier of the CADU product.
        name (str): The name of the CADU product.
        local (str, optional): The local path where the CADU product will be downloaded.
        obs (str, optional): The observation identifier associated with the CADU product.
        db (Database): The database connection object.

    Returns:
        dict: A dictionary indicating whether the download process has started.

    Raises:
        None
    """

    # Does the product download status already exist in database ? Filter on the EOP ID.
    query = db.query(CaduProduct).where(CaduProduct.file_id == file_id)
    if query.count():
        # Get the existing product and overwrite the download status.
        # TODO: should we keep download history in a distinct table and init a new download entry ?
        product = query.first()
        update_db(db, product, DownloadStatus.NOT_STARTED)

    # Else init a new entry from the input arguments
    else:
        product = CaduProduct(file_id=file_id, name=name, status=DownloadStatus.NOT_STARTED)
        db.add(product)
        db.commit()

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
            product.id,
            file_id,
            name,
            local,
            obs,
            secrets,
        ),
    )
    thread.start()

    # check the start of the thread
    if not thread_started.wait(timeout=DWN_THREAD_START_TIMEOUT):
        print("Download thread did not start !")
        # update the status in database
        update_db(db, product, DownloadStatus.FAILED, "Download thread did not start !")
        return {"started": "false"}

    # update the status in database
    update_db(db, product, DownloadStatus.IN_PROGRESS)

    return {"started": "true"}
