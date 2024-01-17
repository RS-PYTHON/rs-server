from sqlalchemy import Column, DateTime, Enum, Integer, String, orm
from services.common.models.product_download_status import (
    EDownloadStatus,
    ProductDownloadStatus,
)

from db import Base


class CaduDownloadStatus(Base):
    __tablename__ = "cadu_download_status"
    __table_args__ = {"extend_existing": True}
    status: EDownloadStatus = Column(Enum(EDownloadStatus), default=EDownloadStatus.NOT_STARTED)

    def __init__(self, *args, **kwargs):
        """Invoked when creating a new record in the database table."""
        super().__init__(*args, **kwargs)
