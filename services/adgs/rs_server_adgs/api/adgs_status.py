"""AUX status HTTP endpoints."""


from fastapi import APIRouter, Depends
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.db.schemas.download_status_schema import DownloadStatusRead
from sqlalchemy.orm import Session

router = APIRouter(tags=adgs_tags)


@router.get("/adgs/aux/status", response_model=DownloadStatusRead)
def get_status(name: str, db: Session = Depends(get_db)):
    """
    Get a product download status from its ID or name.

    :param str name: AUX name
    :param Session db: database session
    """
    return AdgsDownloadStatus.get(name=name, db=db)
