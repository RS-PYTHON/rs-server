"""AUX status HTTP endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import EDownloadStatus
from sqlalchemy.orm import Session

router = APIRouter(tags=adgs_tags)

####################
# DATABASE SCHEMAS #
####################


class AdgsProductBase(BaseModel):
    """
    AdgsDownloadStatus fields that are known when both reading and creating the object.
    """

    product_id: str
    name: str
    available_at_station: datetime | None


# Read schema = fields that are known when reading but not creating the object.
class AdgsProductRead(AdgsProductBase):
    """
    AdgsDownloadStatus fields that are known when reading but not when creating the object.
    """

    db_id: int
    download_start: datetime | None = None
    download_stop: datetime | None = None
    status: EDownloadStatus
    status_fail_message: str | None = None

    model_config = ConfigDict(from_attributes=True)  # build models using python object attributes


##################
# HTTP ENDPOINTS #
##################


@router.get("/adgs/aux/status", response_model=AdgsProductRead)
def get_status(name: str, db: Session = Depends(get_db)):
    """
    Get a product download status from its ID or name.

    :param str name: AUX name
    :param Session db: database session
    """
    return AdgsDownloadStatus.get(name=name, db=db)
