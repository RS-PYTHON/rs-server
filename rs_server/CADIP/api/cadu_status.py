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

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

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
 
dwn_status_to_string = {DownloadStatus.NOT_STARTED: "not_started",
                         DownloadStatus.IN_PROGRESS: "in_progress",
                         DownloadStatus.FAILED: "failed",
                         DownloadStatus.DONE: "done",} 


@router.get("/cadip/{station}/cadu/status")
def get_status(station: str, file_id: str, name: str, db=Depends(get_db)):
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
    if len(file_id) > 0:
        query = db.query(CaduProduct).where(CaduProduct.file_id == file_id)
    elif len(name) > 0:
        query = db.query(CaduProduct).where(CaduProduct.name == name)
    else:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="invalid input parameters")
    
    if query.count():
        # Get the existing product and overwrite the download status.
        # TODO: should we keep download history in a distinct table and init a new download entry ?
        product = query.first()     
        print("GET_STATUS: %s | Returning: %s ", product, dwn_status_to_string[product.status])   
        return JSONResponse(status_code=status.HTTP_200_OK, content = dwn_status_to_string[product.status])
    else:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Product not found")

