"""Docstring will be written here."""
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from db.database import get_db
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from rs_server_common.utils.logging import Logging

from rs_server.api_common.utils import EoDAGDownloadHandler, update_db
from services.adgs.rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from services.adgs.rs_server_adgs.adgs_retriever import init_adgs_retriever
from services.common.models.product_download_status import EDownloadStatus

router = APIRouter(tags=["AUX products"])

logger = Logging.default(__name__)


def local_start_eodag_download(argument: EoDAGDownloadHandler):
    """Docstring will be written here."""
    with contextmanager(get_db)() as db:
        try:
            db_product = AdgsDownloadStatus.get(db, name=argument.name)
            local = Path("/tmp" if not argument.local else argument.local)
            data_retriever = init_adgs_retriever(None, None, local)
            # Update the status to IN_PROGRESS in the database
            db_product.in_progress(db)
            argument.thread_started.set()
            data_retriever.download(argument.product_id, argument.name)
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
    """Docstring will be written here."""
    try:
        db_product = AdgsDownloadStatus.get(db, name=name)
        product_id = db_product.product_id
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
