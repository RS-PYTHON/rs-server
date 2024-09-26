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

"""Module used to download AUX files from ADGS station."""

import tempfile
import threading
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_adgs.adgs_retriever import init_adgs_provider
from rs_server_common.authentication.authentication import auth_validator
from rs_server_common.authentication.authentication_to_external import (
    set_eodag_auth_token,
)
from rs_server_common.db.database import get_db
from rs_server_common.db.models.download_status import EDownloadStatus
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    DWN_THREAD_START_TIMEOUT,
    EoDAGDownloadHandler,
    eodag_download,
    update_db,
)
from sqlalchemy.orm import Session

router = APIRouter(tags=adgs_tags)

logger = Logging.default(__name__)


def start_eodag_download(argument: EoDAGDownloadHandler):
    """Start the eodag download process.

    This function initiates the eodag download process using the provided arguments. It sets up
    the temporary directory where the files are to be downloaded and gets the database handler

    Args:
        argument (EoDAGDownloadHandler): An instance of EoDAGDownloadHandler containing the arguments used in the
    downloading process

    """
    # Open a database sessions in this thread, because the session from the root thread may have closed.
    try:
        with tempfile.TemporaryDirectory() as default_temp_path, contextmanager(get_db)() as db:
            eodag_download(
                argument,
                db,
                init_adgs_provider,
                default_path=default_temp_path,
            )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Exception caught: {e}")


class AdgsDownloadResponse(BaseModel):
    """Endpoint response"""

    started: bool


@router.get("/adgs/aux", response_model=AdgsDownloadResponse)
@auth_validator(station="adgs", access_type="download")
def download_products(
    request: Request,  # pylint: disable=unused-argument
    name: Annotated[str, Query(description="AUX product name")],
    local: Annotated[str | None, Query(description="Local download directory")] = None,
    obs: Annotated[str | None, Query(description='Object storage path e.g. "s3://bucket-name/sub/dir"')] = None,
    db: Session = Depends(get_db),
):
    """Initiate an asynchronous download process for an ADGS product using EODAG.

    This endpoint triggers the download of an ADGS product identified by the given
    name of the file. It starts the download process in a separate thread
    using the start_eodag_download function and updates the product's status in the database.

    Args:
        request (Request): The request object (unused).
        name (str): AUX product name.
        local (str, optional): Local download directory.
        obs (str, optional): Object storage path (e.g., "s3://bucket-name/sub/dir").
        db (Session): The database connection object.

    Returns:
        JSONResponse (starlette.responses): A JSON response indicating whether the download process has started.

    """

    try:
        set_eodag_auth_token("adgs", "auxip")
        db_product = AdgsDownloadStatus.get(db, name=name)
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(exception)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"started": "false"},
        )

    # Reset status to not_started
    db_product.not_started(db)

    # start a thread to run the action in background
    thread_started = threading.Event()
    # fmt: off
    eodag_args = EoDAGDownloadHandler(
        AdgsDownloadStatus, thread_started, "adgs", str(db_product.product_id),
        name, local, obs,
    )
    # fmt: on
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
