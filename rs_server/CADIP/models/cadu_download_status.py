"""CADU Product model implementation."""

import enum

from sqlalchemy import Column, DateTime, Enum, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession

from rs_server.db.database import Base


class EDownloadStatus(enum.Enum):
    """
    Download status enumeration.
    """

    NOT_STARTED = 1
    IN_PROGRESS = 2
    FAILED = 3
    DONE = 4


class CaduDownloadStatus(Base):
    """
    Download status model implemnetation.

    :param int db_id: auto-incremented database ID.
    :param str cadu_id: CADU ID e.g. "2b17b57d-fff4-4645-b539-91f305c27c69"
    :param str name: CADU name e.g. "DCS_04_S1A_20231121072204051312_ch1_DSDB_00001.raw"
    :param DateTime available_at_station: available datetime for download. T0 for the timeliness.
    :param DateTime download_start: rs-server download start time from CADIP station into local then S3 bucket.
    :param DateTime download_stop: download stop time, idem.
    :param EDownloadStatus status: download status value, idem.
    :param str status_fail_message: explanation message if the download failed.
    """

    __tablename__ = "cadu_download_status"

    db_id = Column(Integer, primary_key=True, index=True, nullable=True)
    cadu_id = Column(String, unique=True, index=True)
    name = Column(String, unique=True, index=True)
    available_at_station = Column(DateTime)
    download_start = Column(DateTime)
    download_stop = Column(DateTime)
    status: EDownloadStatus = Column(Enum(EDownloadStatus), default=EDownloadStatus.NOT_STARTED)
    status_fail_message = Column(String)

    #######################
    # DATABASE OPERATIONS #
    #######################

    @classmethod
    async def create(cls, db: AsyncSession, **kwargs):
        """Create entry in database table."""
        entry = cls(**kwargs)
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry
