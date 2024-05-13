# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Module used to implement abstract model of an SQLAlchemy table."""

from __future__ import annotations

import enum
from datetime import datetime
from threading import Lock

from fastapi import HTTPException
from rs_server_common.db import Base
from sqlalchemy import Column, DateTime, Integer, String, orm
from sqlalchemy.orm import Session

# pylint: disable=attribute-defined-outside-init
# mypy: ignore-errors
# Ignore pylint and mypy false positive errors on sqlalchemy


class EDownloadStatus(str, enum.Enum):
    """
    Download status enumeration.
    """

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED = "FAILED"
    DONE = "DONE"


class DownloadStatus(Base):
    """Abstract implementation of SQLAlchemy Base"""

    __abstract__ = True  # this class must be inherited

    db_id = Column(Integer, primary_key=True, index=True, nullable=True)
    product_id = Column(String, unique=True, index=True)
    name = Column(String, unique=True, index=True)
    available_at_station = Column(DateTime)
    download_start = Column(DateTime)
    download_stop = Column(DateTime)
    status_fail_message = Column(String)

    def __init__(self, *args, **kwargs):
        """Invoked when creating a new record in the database table."""
        super().__init__(*args, **kwargs)
        self.lock = Lock()

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
    def get(cls, db: Session, name: str | Column[str], raise_if_missing=True) -> DownloadStatus | None:
        """
        Get single database table entry by name.

        Args:
            db (Session): Database session
            name (str): Product name
            raise_if_missing (bool): if product is missing, raise Exception or return None.

        Returns:
            DownloadStatus: database table entry
        """

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
    def get_if_exists(cls, *args, **kwargs) -> DownloadStatus:
        """
        Get single database entry by name if it exists, else None.

        Calls :func:`~get` with `raise_if_missing=False`
        """
        return cls.get(*args, **kwargs, raise_if_missing=False)

    @classmethod
    def create(cls, db: Session, **kwargs) -> DownloadStatus:
        """
        Create and return database entry.

        Args:
            db (Session): Database session
            kwargs: Any :func:`~DownloadStatus` attributes.
        """
        entry = cls(**kwargs)
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
