"""CADU Product model implementation."""

from __future__ import annotations

import enum
from datetime import datetime
from threading import Lock

from fastapi import HTTPException
from rs_server_common.db import Base
from sqlalchemy import Column, DateTime, Enum, Integer, String, orm
from sqlalchemy.orm import Session


class EDownloadStatus(enum.Enum):
    """
    Download status enumeration.
    """

    NOT_STARTED = 1
    IN_PROGRESS = 2
    FAILED = 3
    DONE = 4


# mypy: ignore-errors
# Ignore mypy false positive errors on sqlalchemy


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
    product_id = Column(String, unique=True, index=True)
    name = Column(String, unique=True, index=True)
    available_at_station = Column(DateTime)
    download_start = Column(DateTime)
    download_stop = Column(DateTime)
    status: EDownloadStatus = Column(Enum(EDownloadStatus), default=EDownloadStatus.NOT_STARTED)
    status_fail_message = Column(String)

    def __init__(self, *args, **kwargs):
        """Invoked when creating a new record in the database table."""
        super().__init__(*args, **kwargs)
        self.lock = Lock()

    def __setitem__(self, item, value):
        """Used to set members at runtime."""
        if hasattr(self, item):
            setattr(self, item, value)
        else:
            raise KeyError()

    @orm.reconstructor
    def init_on_load(self):
        """Invoked when retrieving an existing record from the database table."""
        self.lock = Lock()

    def not_started(self, db: Session):
        """Update database entry to not started."""
        with self.lock:
            self.status = EDownloadStatus.NOT_STARTED
            self.download_start = None
            self.download_stop = None
            self.status_fail_message = None
            db.commit()
            db.refresh(self)

    def in_progress(self, db: Session, download_start: datetime = None):
        """Update database entry to progress."""
        with self.lock:
            self.status = EDownloadStatus.IN_PROGRESS
            self.download_start = download_start or datetime.now()
            self.download_stop = None
            self.status_fail_message = None
            db.commit()
            db.refresh(self)

    def failed(self, db: Session, status_fail_message: str, download_stop: datetime = None):
        """Update database entry to failed."""
        with self.lock:
            self.status = EDownloadStatus.FAILED
            self.download_stop = download_stop or datetime.now()
            self.status_fail_message = status_fail_message
            db.commit()
            db.refresh(self)

    def done(self, db: Session, download_stop: datetime = None):
        """Update database entry to done."""
        with self.lock:
            self.status = EDownloadStatus.DONE
            self.download_stop = download_stop or datetime.now()
            self.status_fail_message = None
            db.commit()
            db.refresh(self)

    #######################
    # DATABASE OPERATIONS #
    #######################

    @classmethod
    def get(cls, db: Session, name: str | Column[str], raise_if_missing=True) -> CaduDownloadStatus:
        """Get single entry by name."""

        # Check if entry exists
        query = db.query(cls).where(cls.name == name)
        if query.count():
            db.refresh(query.first())
            return query.first()

        # Else raise and Exception if asked
        if raise_if_missing:
            raise HTTPException(
                status_code=404,
                detail=f"No {cls.__name__} entry found in table {cls.__tablename__!r} for name={name!r}",
            )

        # Else return None result
        return None

    @classmethod
    def get_if_exists(cls, *args, **kwargs) -> CaduDownloadStatus | None:
        """Get single entry by name if it exists, else None"""
        return cls.get(*args, **kwargs, raise_if_missing=False)

    @classmethod
    def create(
        cls,
        db: Session,
        **kwargs,
    ) -> CaduDownloadStatus:
        """Create and return entry"""
        entry = cls(**kwargs)
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
