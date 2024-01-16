"""Docstring will be written here."""
import threading
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from rs_server_common.utils.logging import Logging

from rs_server.api_common.utils import EoDAGDownloadHandler
from services.adgs.rs_server_adgs.adgs_retriever import init_adgs_retriever

router = APIRouter(tags=["AUX products"])

logger = Logging.default(__name__)


def local_start_eodag_download(argument: EoDAGDownloadHandler):
    """Docstring will be written here."""
    local = Path("/tmp" if not argument.local else argument.local)
    data_retriever = init_adgs_retriever(None, None, local)
    data_retriever.download(argument.product_id, argument.name)


@router.get("/adgs/aux")
def download(
    name: str,
    local: Optional[str] = None,
    obs: Optional[str] = None,
    # db=Depends(get_db))
):
    """Docstring will be written here."""
    # disabled
    # try:
    #    db_product = ProductDownloadStatus.get(db, name=name)
    #    # Use a const ID for first implementation
    product_id = "2b17b57d-fff4-4645-b539-91f305c27c69"
    # except Exception as exception:  # pylint: disable=broad-exception-caught
    #    logger.error(exception)
    #    return JSONResponse(
    #        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    #        content={"started": "false"},
    #    )

    # start a thread to run the action in background
    thread_started = threading.Event()
    eodag_args = EoDAGDownloadHandler(thread_started, "ADGS", product_id, name, local, obs)

    thread = threading.Thread(
        target=local_start_eodag_download,
        args=(eodag_args,),
    )
    thread.start()
