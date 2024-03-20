"""Pydantic schemas for DownloadStatus."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer
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

    @field_serializer("available_at_station", "download_start", "download_stop")
    def serialize_dt(self, dt: datetime | None, _info):
        """
        Called by the HTTP endpoint to convert a datetime into a JSON string.
        """
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") if dt else None
