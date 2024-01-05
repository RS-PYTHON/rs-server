from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from rs_server.db.models.download_status import DownloadStatus


# Base schema = fields that are known when both reading and creating the object.
class CaduProductBase(BaseModel):
    file_id: str
    name: str
    available_at_station: datetime


# Read schema = fields that are known when reading but not creating the object.
class CaduProductRead(CaduProductBase):
    id: int  # auto-incremented id
    downlink_start: Optional[datetime]  # set when the caller starts the download
    downlink_stop: Optional[datetime]  # set when the caller finishes the download
    status: DownloadStatus  # updated during the download
    status_fail_message: Optional[str]  # updated during the download

    class Config:
        orm_mode = True


# Create schema = fields known at creation that we don't want to read e.g. password
class CaduProductCreate(CaduProductBase):
    pass


##################
# Update schemas #
##################


class CaduProductDownloadStart(BaseModel):
    downlink_start: datetime


class CaduProductDownloadDone(BaseModel):
    downlink_stop: datetime


class CaduProductDownloadFail(BaseModel):
    downlink_stop: datetime
    status_fail_message: str
