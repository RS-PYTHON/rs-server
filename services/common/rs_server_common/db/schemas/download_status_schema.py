"""Pydantic schemas for DownloadStatus."""


from datetime import datetime

from pydantic import BaseModel, ConfigDict
from rs_server_common.db.models.download_status import EDownloadStatus


class DownloadStatusBase(BaseModel):
    """DownloadStatus fields that are known when both reading and creating the object."""

    product_id: str
    name: str
    available_at_station: datetime | None


class ReadDownloadStatus(DownloadStatusBase):
    """DownloadStatus fields that are known when reading but not when creating the object."""

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
