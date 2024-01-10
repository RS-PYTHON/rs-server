"""CADU Product model implementation."""

from __future__ import annotations

import enum
from datetime import datetime
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import Column, DateTime, Enum, Integer, String
from sqlalchemy.exc import NoResultFound
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = Lock()

    def not_started(self, db: AsyncSession):
        """Update database entry to not started."""
        with self.lock:
            self.status = EDownloadStatus.IN_PROGRESS
            self.download_start = None
            self.download_stop = None
            self.status_fail_message = None
            db.commit()

    def in_progress(self, db: AsyncSession, download_start: datetime = datetime.now()):
        """Update database entry to progress."""
        with self.lock:
            self.status = EDownloadStatus.IN_PROGRESS
            self.download_start = download_start
            self.download_stop = None
            self.status_fail_message = None
            db.commit()

    def failed(self, db: AsyncSession, status_fail_message: str, download_stop: datetime = datetime.now()):
        """Update database entry to failed."""
        with self.lock:
            self.status = EDownloadStatus.FAILED
            self.download_stop = download_stop
            self.status_fail_message = status_fail_message
            db.commit()

    def done(self, db: AsyncSession, download_stop: datetime = datetime.now()):
        """Update database entry to done."""
        with self.lock:
            self.status = EDownloadStatus.DONE
            self.download_stop = download_stop
            self.status_fail_message = None
            db.commit()

    #######################
    # DATABASE OPERATIONS #
    #######################

    @classmethod
    def get_all(cls, db: AsyncSession, **kwargs) -> list[CaduDownloadStatus]:
        """Get all entries in database table."""
        return db.query(cls).all()

    @classmethod
    def get(cls, db: AsyncSession, cadu_id: str, name: str) -> CaduDownloadStatus:
        """Get single entry by CADU ID or name."""
        try:
            return db.query(cls).where((cls.cadu_id == cadu_id) | (cls.name == name)).one()
        except NoResultFound as exception:
            raise NoResultFound(f"No {cls.__name__} found for cadu_id={cadu_id!r} or name={name!r}") from exception

    @classmethod
    def create(cls, db: AsyncSession, **kwargs) -> CaduDownloadStatus:
        """Create entry in database table."""
        entry = cls(**kwargs)
        db.add(entry)
        db.commit()
        return entry
