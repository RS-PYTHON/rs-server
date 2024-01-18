"""Module used to download CADU files."""
import asyncio
import os
import os.path as osp
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Event

from db.database import get_db
from eodag import setup_logging
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from rs_server_common.utils.logging import Logging
from s3_storage_handler.s3_storage_handler import (
    PrefectPutFilesToS3Config,
    S3StorageHandler,
    prefect_put_files_to_s3,
)

from rs_server.api_common.utils import EoDAGDownloadHandler, update_db
from services.cadip.rs_server_cadip.cadip_retriever import init_cadip_data_retriever
from services.cadip.rs_server_cadip.cadu_download_status import CaduDownloadStatus
from services.common.models.product_download_status import EDownloadStatus

# TODO: the value was set to 1.8s but it sometimes doesn't pass the CI in github.
DWN_THREAD_START_TIMEOUT = 5

router = APIRouter(tags=["Cadu products"])

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent.parent / "services" / "cadip" / "config"

logger = Logging.default(__name__)


def start_eodag_download(argument: EoDAGDownloadHandler):
    """Start an EODAG download process for a specified product.

    This function initiates a download process using EODAG to retrieve a product with the given
    parameters. It also updates the product's status in the database based on the download result.

    Args:
        station (str): The EODAG station identifier.
        cadu_id (str): The CADU identifier of the product.
        name (str): The name of the product.
        local (str): The local path where the product will be downloaded.
        obs (str, optional): The observation identifier associated with the product.

    Returns:
        None

    Raises:
        None
    """
    # Open a database sessions in this thread, because the session from the root thread may have closed.
    with contextmanager(get_db)() as db:
        # Get the product download status
        db_product = CaduDownloadStatus.get(db, name=argument.name)

        # init eodag object
        try:
            logger.debug(
                "%s : %s : %s: Thread started !",
                os.getpid(),
                threading.get_ident(),
                datetime.now(),
            )

            setup_logging(3, no_progress_bar=True)

            local = Path("/tmp" if not argument.local else argument.local)

            data_retriever = init_cadip_data_retriever(argument.station, None, None, local)

            # Update the status to IN_PROGRESS in the database
            db_product.in_progress(db)
            # notify the main thread that the download will be started
            argument.thread_started.set()
            init = datetime.now()
            data_retriever.download(argument.product_id, argument.name)
            logger.info(
                "%s : %s : File: %s downloaded in %s",
                os.getpid(),
                threading.get_ident(),
                argument.name,
                datetime.now() - init,
            )
        except Exception as exception:  # pylint: disable=broad-exception-caught
            # Pylint disabled since error is logged here.
            logger.error(
                "%s : %s : %s: Exception caught: %s",
                os.getpid(),
                threading.get_ident(),
                datetime.now(),
                exception,
            )

            # Try n times to update the status to FAILED in the database
            update_db(db, db_product, EDownloadStatus.FAILED, repr(exception))
            return

        if argument.obs:
            try:
                # NOTE: The environment variables have to be set from outside
                # otherwise the connection with s3 endpoint fails
                secrets = {
                    "s3endpoint": os.environ["S3_ENDPOINT"],
                    "accesskey": os.environ["S3_ACCESSKEY"],
                    "secretkey": os.environ["S3_SECRETKEY"],
                }
                s3_handler = S3StorageHandler(
                    secrets["accesskey"],
                    secrets["secretkey"],
                    secrets["s3endpoint"],
                    "sbg",
                )
                obs_array = argument.obs.split("/")
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
                # Try n times to update the status to FAILED in the database
                update_db(
                    db,
                    db_product,
                    EDownloadStatus.FAILED,
                    "Could not connect to the s3 storage",
                )
                return
            finally:
                os.remove(data_retriever.filename)

        # Try n times to update the status to DONE in the database
        update_db(db, db_product, EDownloadStatus.DONE)
        logger.debug("Download finished succesfully for %s", db_product.name)


@router.get("/cadip/{station}/cadu")
def download(
    station: str,
    name: str,
    local: str = "",
    obs: str = "",
    db=Depends(get_db),
):  # pylint: disable=too-many-arguments
    """Initiate an asynchronous download process for a CADU product using EODAG.

    This endpoint triggers the download of a CADU product identified by the given
    name, and observation identifier. It starts the download process in a separate thread
    using the start_eodag_download function and updates the product's status in the database.

    Args:
        station (str): The EODAG station identifier.
        name (str): The name of the CADU product.
        local (str, optional): The local path where the CADU product will be downloaded.
        obs (str, optional): The observation identifier associated with the CADU product.
        db (Database): The database connection object.

    Returns:
        dict: A dictionary indicating whether the download process has started.

    Raises:
        None
    """

    # Get the product download status from database
    try:
        db_product = CaduDownloadStatus.get(db, name=name)
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(exception)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"started": "false"},
        )

    # start a thread to run the action in background
    logger.debug(
        "%s : %s : %s: MAIN THREAD: Starting thread, local = %s",
        os.getpid(),
        threading.get_ident(),
        datetime.now(),
        locals(),
    )

    thread_started = Event()
    eodag_args = EoDAGDownloadHandler(thread_started, station, str(db_product.cadu_id), name, local, obs)
    # Big note / TODO here
    # Is there a mechanism to catch / capture return value from a function running inside a thread?
    # If start_eodag_download throws an error, there is no simple solution to return it with FastAPI
    thread = threading.Thread(
        target=start_eodag_download,
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
