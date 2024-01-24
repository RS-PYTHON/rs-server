"""CADU status HTTP endpoints."""


from fastapi import APIRouter, Depends
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadu_download_status import CaduDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.db.schemas.download_status_schema import DownloadStatusRead
from sqlalchemy.orm import Session

router = APIRouter(tags=cadip_tags)


@router.get("/cadip/{station}/cadu/status", response_model=DownloadStatusRead)
def get_status(name: str, db: Session = Depends(get_db)):
    """
    Get a product download status from its ID or name.

    :param str name: CADU name e.g. "DCS_04_S1A_20231121072204051312_ch1_DSDB_00001.raw"
    :param Session db: database session
    """
    return CaduDownloadStatus.get(name=name, db=db)
