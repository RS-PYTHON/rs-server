"""ADGS Product model implementation."""

from __future__ import annotations

from rs_server_common.models.product_download_status import (
    EDownloadStatus,
    ProductDownloadStatus,
)
from sqlalchemy import Column, Enum


class AdgsDownloadStatus(ProductDownloadStatus):
    """Class used to implement DB CRUD ops for AUX products."""

    __tablename__ = "adgs_download_status"
    status: EDownloadStatus = Column(Enum(EDownloadStatus), default=EDownloadStatus.NOT_STARTED)
