from sqlalchemy import Column, Enum

from services.common.models.product_download_status import (
    EDownloadStatus,
    ProductDownloadStatus,
)


class AdgsDownloadStatus(ProductDownloadStatus):
    __tablename__ = "adgs_download_status"
    __table_args__ = {"extend_existing": True}
    status: EDownloadStatus = Column(Enum(EDownloadStatus), default=EDownloadStatus.NOT_STARTED)

    def __init__(self, status):
        """Invoked when creating a new record in the database table."""
        self.status = status
        super().__init__()
