from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rs_server.CADIP.models.cadu_download_status import CaduDownloadStatus as CDS
from rs_server.CADIP.models.cadu_download_status import EDownloadStatus
from rs_server.db.database import get_db

router = APIRouter(tags=["Cadu products"])

####################
# DATABASE SCHEMAS #
####################


class CaduProductBase(BaseModel):
    """
    CaduDownloadStatus fields that are known when both reading and creating the object.
    """

    cadu_id: str
    name: str
    available_at_station: datetime


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

    model_config = ConfigDict(from_attributes=True)  # build models using python object attributes


##################
# HTTP ENDPOINTS #
##################


@router.get("/cadip/{station}/cadu/status", response_model=CaduProductRead)
async def get_status(cadu_id: str, name: str, db: AsyncSession = Depends(get_db)):
    """
    Get a product download status from its ID and name.
    """
    return (await db.execute(select(CDS).where(CDS.cadu_id == cadu_id).where(CDS.name == name))).one()
