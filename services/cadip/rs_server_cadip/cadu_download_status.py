"""CADU Product model implementation."""

from __future__ import annotations

from rs_server_common.models.product_download_status import (
    EDownloadStatus,
    ProductDownloadStatus,
)
from sqlalchemy import Column, Enum


class CaduDownloadStatus(ProductDownloadStatus):
    """Class used to implement DB CRUD ops for CADU products."""

    __tablename__ = "cadu_download_status"

    # I have errors when implementing the enum field in the parent class, I don't know why
    status: EDownloadStatus = Column(Enum(EDownloadStatus), default=EDownloadStatus.NOT_STARTED)

    def __init__(self, *args, status: EDownloadStatus = EDownloadStatus.NOT_STARTED, **kwargs):
        """Invoked when creating a new record in the database table."""
        super().__init__(*args, **kwargs)
        self.status = status
