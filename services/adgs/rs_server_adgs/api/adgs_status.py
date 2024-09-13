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

"""HTTP endpoints to get the downloading status from ADGS stations."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_common.authentication.authentication import auth_validator
from rs_server_common.db.database import get_db
from rs_server_common.schemas.download_status_schema import ReadDownloadStatus
from sqlalchemy.orm import Session

router = APIRouter(tags=adgs_tags)


@router.get("/adgs/aux/status", response_model=ReadDownloadStatus)
@auth_validator(station="adgs", access_type="download")
def get_download_status(
    request: Request,  # pylint: disable=unused-argument
    name: Annotated[str, Query(description="AUX product name")],
    db: Session = Depends(get_db),
):
    """
    Get a product download status from its ID or name.

    Args:
        request (Request): The request object (unused).
        name (str): The name of the AUX product.
        db (Session): The database connection object.

    Returns:
        ReadDownloadStatus (DownloadStatus): The download status of the specified AUX product.

    Raises:
        HTTPException: If the product is not found in the database.
    """

    return AdgsDownloadStatus.get(name=name, db=db)
