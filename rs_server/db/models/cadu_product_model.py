"""CADU Product model implementation."""

from sqlalchemy import Column, DateTime, Enum, Integer, String

from rs_server.db.models.download_status import DownloadStatus
from rs_server.db.session import Base


class CaduProduct(Base):
    """CADU Product model implementation."""

    __tablename__ = "cadu_products"

    # See: https://pforge-exchange2.astrium.eads.net/jira/browse/RSPY-72
    # TOOD: it's not very clear what each field does.
    # Do we also need the file path on the CADU station (download from) and S3 server or local disk (uploaded to) ?

    id = Column(Integer, primary_key=True, index=True)
    # TODO: add a CADU identifier ?

    name = Column(String, unique=True, index=True)  # CADU name
    available_at_station = Column(DateTime)  # When the product is available for download at the CADU station

    # TODO: downlink start and stop datetimes from satellite to CADU station ?
    # Or download from CADU station to S3 and/or local disk ?
    # Let's start on the 2nd hypothesis for now.
    downlink_start = Column(DateTime)
    downlink_stop = Column(DateTime)

    # Download status from CADU station to S2 and/or local disk
    status: DownloadStatus = Column(Enum(DownloadStatus), default=DownloadStatus.NOT_STARTED)

    # Explanation message if the download failed.
    status_fail_message = Column(String)

    # TODO: can the product be downloaded several times ? e.g. if the first download failed
    # or if several users in laptop mode downloaded the product.
