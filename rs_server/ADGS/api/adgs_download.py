"""Module used to download AUX files from ADGS station."""
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_adgs.adgs_retriever import init_adgs_retriever
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import EDownloadStatus
from rs_server_common.utils.logging import Logging

from rs_server.api_common.utils import (
    DWN_THREAD_START_TIMEOUT,
    EoDAGDownloadHandler,
    update_db,
)

router = APIRouter(tags=["AUX products"])

logger = Logging.default(__name__)


def local_start_eodag_download(argument: EoDAGDownloadHandler):
    """
    @param argument: Object with properties 'name', 'local', 'thread_started', 'product_id', etc.

    This function downloads an AUX product and updates its status in the database.

    - Retrieves the product from the database based on the provided 'name'.
    - Initializes a data retriever for ADGS with the specified local path.
    - Updates the product's status to IN_PROGRESS in the database.
    - Signals that the download thread has started.
    - Initiates the product download.
    - Attempts to update the product's status to DONE in the database multiple times.
    - Logs a debug message upon successful download completion.
    - In case of any exception during the process, updates the product's status to FAILED in the database.
    - If the download is successful, updates the product's status to DONE in the database.
    - Logs a debug message upon successful download completion.

    @return: None
    """
    with contextmanager(get_db)() as db:
        try:
            db_product = AdgsDownloadStatus.get(db, name=argument.name)
            local = Path("/tmp" if not argument.local else argument.local)
            data_retriever = init_adgs_retriever(None, None, local)
            # Update the status to IN_PROGRESS in the database
            db_product.in_progress(db)
            argument.thread_started.set()
            init = datetime.now()
            data_retriever.download(argument.product_id, argument.name)
            logger.info(
                f"{os.getpid()} : {threading.get_ident()} : File: {argument.name} downloaded in \
                {datetime.now() - init}",
            )
            # Try n times to update the status to DONE in the database
            update_db(db, db_product, EDownloadStatus.DONE)
            logger.debug("Download finished succesfully for %s", db_product.name)
        except Exception as exception:  # pylint: disable=broad-exception-caught
            update_db(db, db_product, EDownloadStatus.FAILED, repr(exception))
            return
    update_db(db, db_product, EDownloadStatus.DONE)
    logger.debug("Download finished succesfully for %s", db_product.name)


@router.get("/adgs/aux")
def download(name: str, local: Optional[str] = None, obs: Optional[str] = None, db=Depends(get_db)):
    """
    Initiates the download of an ADGS product by name.

    This endpoint starts a background thread to download an ADGS product and updates its status in the database.

    @param name: The name of the ADGS product to download.
    @param local: Optional; the local path where the downloaded product should be saved.
    @param obs: Optional; observation parameter for the download.
    @param db: Dependency; the database session.

    - Retrieves the product details from the database using the provided 'name'.
    - In case of any exceptions during retrieval, logs the error and returns a service unavailable response.
    - Starts a new thread to handle the download process in the background.
    - The thread uses 'EoDAGDownloadHandler' to manage the download process.

    @return: A JSON response indicating whether the download process started successfully.
             In case of an error, returns a service unavailable response.
    """
    try:
        db_product = AdgsDownloadStatus.get(db, name=name)
        product_id = str(db_product.product_id)
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(exception)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"started": "false"},
        )

    # start a thread to run the action in background
    thread_started = threading.Event()
    eodag_args = EoDAGDownloadHandler(thread_started, "ADGS", product_id, name, local, obs)

    thread = threading.Thread(
        target=local_start_eodag_download,
        args=(eodag_args,),
    )
    thread.start()

    # check the start of the thread
    if not thread_started.wait(timeout=DWN_THREAD_START_TIMEOUT):
        logger.error("Download thread did not start !")
        # Try n times to update the status to FAILED in the database
        update_db(db, db_product, EDownloadStatus.FAILED, "Download thread did not start !")
        return JSONResponse(status_code=status.HTTP_408_REQUEST_TIMEOUT, content={"started": "false"})

    return JSONResponse(status_code=status.HTTP_200_OK, content={"started": "true"})
