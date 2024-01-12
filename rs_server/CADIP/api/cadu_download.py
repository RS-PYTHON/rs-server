"""Docstring will be here."""
import asyncio
import os
import os.path as osp
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Event

import sqlalchemy
from eodag import setup_logging
from fastapi import APIRouter, Depends
from rs_server_common.utils.logging import Logging

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
from services.cadip.rs_server_cadip.cadip_retriever import init_cadip_data_retriever

DWN_THREAD_START_TIMEOUT = 1.8
tt = 0
router = APIRouter(tags=["Cadu products"])

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent.parent / "services" / "cadip" / "config"

logger = Logging.default(__name__)


def update_db(db, status: CaduDownloadStatus, estatus: EDownloadStatus, status_fail_message=None):
    """Update the database with the status of a product."""

    # Try n times to update the status.
    # Don't do it for NOT_STARTED and IN_PROGRESS (call directly status.not_started or status.in_progress)
    # because it will anyway be overwritten later by DONE or FAILED.

    last_exception = None

    for _ in range(3):
        try:
            if estatus == EDownloadStatus.FAILED:
                status.failed(db, status_fail_message)
            elif estatus == EDownloadStatus.DONE:
                status.done(db)

            # The database update worked, exit function
            return

        # The database update failed, wait n seconds and retry
        except (ConnectionError, sqlalchemy.exc.OperationalError) as exception:
            last_exception = exception
            time.sleep(1)

    # If all attemps failed, raise the last Exception
    raise last_exception


def start_eodag_download(thread_started, station, cadu_id, name, local, obs: str = "", secrets={}):
    """Start an EODAG download process for a specified product.

    This function initiates a download process using EODAG to retrieve a product with the given
    parameters. It also updates the product's status in the database based on the download result.

    Args:
        station (str): The EODAG station identifier.
        cadu_id (str): The CADU identifier of the product.
        name (str): The name of the product.
        local (str): The local path where the product will be downloaded.
        obs (str, optional): The observation identifier associated with the product.
        secrets (dict, optional): Dictionary containing access key, secret key, and S3 endpoint for authentication.

    Returns:
        None

    Raises:
        None
    """
    # Open a database sessions in this thread, because the session from the root thread may have closed.
    with contextmanager(get_db)() as db:
        global tt

        # Get the product download status
        status = CaduDownloadStatus.get(db, cadu_id=cadu_id, name=name)

        # init eodag object
        try:
            logger.debug("%s : %s : %s: Thread started !", os.getpid(), threading.get_ident(), datetime.now())
            # config_file_path = CONF_FOLDER / "cadip_ws_config.yaml"

            setup_logging(3, no_progress_bar=True)

            # eodag_provider = EodagProvider(Path(config_file_path), station)
            if len(local) == 0:
                local = "/tmp"

            data_retriever = init_cadip_data_retriever(station, None, None, Path(local))
            status.in_progress(db)  # updates the database
            # notify the main thread that the download will be started
            thread_started.set()
            init = datetime.now()
            data_retriever.download(cadu_id, name)
            logger.info(
                "%s : %s : File: %s downloaded in %s",
                os.getpid(),
                threading.get_ident(),
                name,
                datetime.now() - init,
            )
        except Exception as exception:
            logger.error(
                "%s : %s : %s: Exception caught: %s",
                os.getpid(),
                threading.get_ident(),
                datetime.now(),
                exception,
            )
            update_db(db, status, EDownloadStatus.FAILED, repr(exception))
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
            except RuntimeError:
                logger.error("Could not connect to the s3 storage")
                update_db(db, status, EDownloadStatus.FAILED, "Could not connect to the s3 storage")
                return
            finally:
                os.remove(data_retriever.filename)

        update_db(db, status, EDownloadStatus.DONE)


@router.get("/cadip/{station}/cadu")
def download(
    station: str,
    cadu_id: str,
    name: str,
    publication_date: str,
    local: str = "",
    obs: str = "",
    db=Depends(get_db),
):
    """Initiate an asynchronous download process for a CADU product using EODAG.

    This endpoint triggers the download of a CADU product identified by the given cadu_id,
    name, and observation identifier. It starts the download process in a separate thread
    using the start_eodag_download function and updates the product's status in the database.

    Args:
        station (str): The EODAG station identifier.
        cadu_id (str): The CADU product identifier.
        name (str): The name of the CADU product.
        local (str, optional): The local path where the CADU product will be downloaded.
        obs (str, optional): The observation identifier associated with the CADU product.
        db (Database): The database connection object.

    Returns:
        dict: A dictionary indicating whether the download process has started.

    Raises:
        None
    """

    # Get or create the product download status in database
    print("ENDPOINT START !")
    # status = CaduDownloadStatus.get_or_create(db, cadu_id, name)
    status = CaduDownloadStatus.get(db, cadu_id=cadu_id, name=name)
    if not status:
        logger.error("Product id %s with name %s could not be found in the database.", cadu_id, name)
        return {"started": "false"}
    # Update the publication date and set the status to not started
    # status.available_at_station = datetime.fromisoformat(publication_date)
    # status.not_started(db)  # updates the database

    # start a thread to run the action in background
    logger.debug(
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
    thread_started = Event()
    thread = threading.Thread(
        target=start_eodag_download,
        args=(
            thread_started,
            station,
            cadu_id,
            name,
            local,
            obs,
            secrets,
        ),
    )
    thread.start()

    # check the start of the thread
    if not thread_started.wait(timeout=DWN_THREAD_START_TIMEOUT):
        # thread_started.clear()
        logger.error("Download thread did not start !")
        # update the status in database
        update_db(db, status, EDownloadStatus.FAILED, "Download thread did not start !")
        return {"started": "false"}
    # thread_started.clear()
    # update the status in database
    # status.in_progress(db)  # updates the database
    return {"started": "true"}
