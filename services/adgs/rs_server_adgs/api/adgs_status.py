"""HTTP endpoints to get the downloading status from ADGS stations."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_common.authentication import apikey_validator
from rs_server_common.db.database import get_db
from rs_server_common.schemas.download_status_schema import ReadDownloadStatus
from sqlalchemy.orm import Session

router = APIRouter(tags=adgs_tags)


@router.get("/adgs/aux/status", response_model=ReadDownloadStatus)
@apikey_validator(station="adgs", access_type="download")
def get_download_status(
    request: Request,  # pylint: disable=unused-argument
    name: Annotated[str, Query(description="AUX product name")],
    db: Session = Depends(get_db),
):
    """
    Get a product download status from its ID or name.
    \f
    Args:
        db (Session): database session

    """

    return AdgsDownloadStatus.get(name=name, db=db)
