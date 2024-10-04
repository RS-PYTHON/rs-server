# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Module used to download CADU files from CADIP stations."""

import os
import os.path as osp
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import Path as FPath
from fastapi import Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_download_status import CadipDownloadStatus, EDownloadStatus
from rs_server_cadip.cadip_retriever import init_cadip_provider
from rs_server_common.authentication.authentication import auth_validator
from rs_server_common.authentication.authentication_to_external import (
    set_eodag_auth_token,
)
from rs_server_common.db.database import get_db
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    DWN_THREAD_START_TIMEOUT,
    EoDAGDownloadHandler,
    eodag_download,
    update_db,
)
from sqlalchemy.orm import Session

router = APIRouter(tags=cadip_tags)

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent.parent / "services" / "cadip" / "config"

logger = Logging.default(__name__)


def start_eodag_download(argument: EoDAGDownloadHandler):
    """Start the eodag download process.

    This function initiates the eodag download process using the provided arguments. It sets up
    the temporary directory where the files are to be downloaded and gets the database handler

    Args:
        argument (EoDAGDownloadHandler): An instance of EoDAGDownloadHandler containing
    the arguments used in the downloading process


    """

    # Open a database sessions in this thread, because the session from the root thread may have closed.
    try:
        with tempfile.TemporaryDirectory() as default_temp_path, contextmanager(get_db)() as db:
            eodag_download(
                argument,
                db,
                init_cadip_provider,
                default_path=default_temp_path,
            )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Exception caught: {e}")


class CadipDownloadResponse(BaseModel):
    """Endpoint response"""

    started: bool


@router.get("/cadip/{station}/cadu", response_model=CadipDownloadResponse)
@auth_validator(station="cadip", access_type="download")
def download_products(
    request: Request,  # pylint: disable=unused-argument
    name: Annotated[str, Query(description="CADU product name")],
    station: str = FPath(description="CADIP station identifier (MTI, SGS, MPU, INU, etc)"),
    local: Annotated[str | None, Query(description="Local download directory")] = None,
    obs: Annotated[str | None, Query(description='Object storage path e.g. "s3://bucket-name/sub/dir"')] = None,
    db: Session = Depends(get_db),
):  # pylint: disable=too-many-arguments
    """Initiate an asynchronous download process for a CADU product using EODAG.

    This endpoint triggers the download of a CADU product identified by the given
    name of the file. It starts the download process in a separate thread
    using the start_eodag_download function and updates the product's status in the database.

    Args:
        request (Request): The request object (unused).
        name (str): CADU product name.
        station (str): CADIP station identifier (e.g., MTI, SGS, MPU, INU).
        local (str, optional): Local download directory. Defaults to None.
        obs (str, optional): Object storage path (e.g., "s3://bucket-name/sub/dir"). Defaults to None.
        db (Session): The database connection object.

    Returns:
        JSONResponse (starlette.responses): A JSON response indicating whether the download process has started.

    Raises:
        HTTPException: If the product is not found in the database.
        HTTPException: If the download thread fails to start.
    """

    # Get the product download status from database
    try:
        db_product = CadipDownloadStatus.get(db, name=name)
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(exception)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"started": "false"},
        )

    set_eodag_auth_token(station.lower(), "cadip")

    db_product.not_started(db)

    # start a thread to run the action in background
    logger.debug(
        "%s : %s : %s: MAIN THREAD: Starting thread, local = %s",
        os.getpid(),
        threading.get_ident(),
        datetime.now(),
        locals(),
    )

    thread_started = Event()
    # fmt: off
    # Skip this function call formatting to avoid the following error: pylint R0801: Similar lines in 2 files
    eodag_args = EoDAGDownloadHandler(
        CadipDownloadStatus, thread_started, station.lower(), str(db_product.product_id),
        name, local, obs,
    )
    # fmt: on
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
