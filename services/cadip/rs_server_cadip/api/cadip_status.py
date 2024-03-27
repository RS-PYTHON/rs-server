"""HTTP endpoints to get the downloading status from CADIP stations."""


from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi import Path as FPath
from fastapi import Query, Request
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_common.authentication import apikey_validator
from rs_server_common.db.database import get_db
from rs_server_common.schemas.download_status_schema import ReadDownloadStatus
from sqlalchemy.orm import Session

router = APIRouter(tags=cadip_tags)


@router.get("/cadip/{station}/cadu/status", response_model=ReadDownloadStatus)
@apikey_validator(station="cadip", access_type="download")
def get_download_status(
    request: Request,  # pylint: disable=unused-argument
    name: Annotated[str, Query(description="CADU product name")],
    db: Session = Depends(get_db),
    station: str = FPath(  # pylint: disable=unused-argument
        description="CADIP station identifier (MTI, SGS, MPU, INU, etc)",
    ),
):
    """
    Get a product download status from its ID or name.
    \f
    Args:
        db (Session): database session
    """

    return CadipDownloadStatus.get(name=name, db=db)
