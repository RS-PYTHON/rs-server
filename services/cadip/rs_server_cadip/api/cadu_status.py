"""CADU status HTTP endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from rs_server_cadip.cadu_download_status import CaduDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import EDownloadStatus
from sqlalchemy.orm import Session

router = APIRouter(tags=["Cadu products"])

####################
# DATABASE SCHEMAS #
####################


class CaduProductBase(BaseModel):
    """
    CaduDownloadStatus fields that are known when both reading and creating the object.
    """

    product_id: str
    name: str
    available_at_station: datetime | None


# Read schema = fields that are known when reading but not creating the object.
class CaduProductRead(CaduProductBase):
    """
    CaduDownloadStatus fields that are known when reading but not when creating the object.
    """

    db_id: int
    download_start: datetime | None = None
    download_stop: datetime | None = None
    status: EDownloadStatus
    status_fail_message: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
        validate_default=True,
        use_enum_values=True,
    )


##################
# HTTP ENDPOINTS #
##################


@router.get("/cadip/{station}/cadu/status", response_model=CaduProductRead)
def get_status(name: str, db: Session = Depends(get_db)):
    """
    Get a product download status from its ID or name.

    :param str name: CADU name e.g. "DCS_04_S1A_20231121072204051312_ch1_DSDB_00001.raw"
    :param Session db: database session
    """
    return CaduDownloadStatus.get(name=name, db=db)
