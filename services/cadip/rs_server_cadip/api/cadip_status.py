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

"""HTTP endpoints to get the downloading status from CADIP stations."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import Path as FPath
from fastapi import Query, Request
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_common.authentication.authentication import auth_validator
from rs_server_common.db.database import get_db
from rs_server_common.schemas.download_status_schema import ReadDownloadStatus
from sqlalchemy.orm import Session

router = APIRouter(tags=cadip_tags)


@router.get("/cadip/{station}/cadu/status", response_model=ReadDownloadStatus)
@auth_validator(station="cadip", access_type="download")
def get_download_status(
    request: Request,  # pylint: disable=unused-argument
    name: Annotated[str, Query(description="CADU product name")],
    db: Session = Depends(get_db),
    station: str = FPath(  # pylint: disable=unused-argument
        description="CADIP station identifier (MTI, SGS, MPU, INU, etc)",
    ),
):
    """
    Get the download status of a CADU product by its name.

    This endpoint retrieves the download status of a CADU product from the database
    using the provided product name.

    Args:
        request (Request): The request object (unused).
        name (str): CADU product name.
        db (Session): The database connection object.
        station (str): CADIP station identifier (e.g., MTI, SGS, MPU, INU).

    Returns:
        ReadDownloadStatus (DownloadStatus): The download status of the product.
    """

    return CadipDownloadStatus.get(name=name, db=db)
