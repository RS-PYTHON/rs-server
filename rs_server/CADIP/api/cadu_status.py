"""Docstring will be here."""
import os.path as osp
from pathlib import Path
from threading import Event


from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from rs_server.db.models.cadu_product_model import CaduProduct
from rs_server.db.models.download_status import DownloadStatus
from rs_server.db.session import get_db

from rs_server_common.utils.logging import Logging

DWN_THREAD_START_TIMEOUT = 1.8
thread_started = Event()
router = APIRouter()

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent.parent / "services" / "cadip" / "config"

logger = Logging.default(__name__)
 
dwn_status_to_string = {DownloadStatus.NOT_STARTED: "not_started",
                         DownloadStatus.IN_PROGRESS: "in_progress",
                         DownloadStatus.FAILED: "failed",
                         DownloadStatus.DONE: "done",} 


@router.get("/cadip/{station}/cadu/status")
def get_status(station: str, file_id: str, name: str, db=Depends(get_db)):    
    """Retrieve the download status of a CADU product.

    This endpoint retrieves and returns the download status of a CADU product identified by either
    the file_id or the name. It checks the database for the product's status and responds with the
    corresponding status string.

    Args:
        station (str): The EODAG station identifier.
        file_id (str): The file identifier of the CADU product.
        name (str): The name of the CADU product.
        db (Database): The database connection object.

    Returns:
        JSONResponse: A JSON response containing the download status of the CADU product.

    Raises:
        JSONResponse: A JSON response with a 400 status code if the input parameters are invalid or
                      if the product is not found in the database.
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
        logger.debug("GET_STATUS: %s | Returning: %s ", product, dwn_status_to_string[product.status])   
        return JSONResponse(status_code=status.HTTP_200_OK, content = dwn_status_to_string[product.status])
    else:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Product not found")

