import enum
from datetime import datetime
from threading import Lock

from fastapi import HTTPException
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


from sqlalchemy.orm import declarative_base


class ProductDownloadStatus:
    __abstract__ = True

    db_id = Column(Integer, primary_key=True, index=True, nullable=True)
    product_id = Column(String, unique=True, index=True)
    name = Column(String, unique=True, index=True)
    available_at_station = Column(DateTime)
    download_start = Column(DateTime)
    download_stop = Column(DateTime)
    status = Column(String)
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
            self.status = str(EDownloadStatus.NOT_STARTED)
            self.download_start = None
            self.download_stop = None
            self.status_fail_message = None
            db.commit()
            db.refresh(self)

    def in_progress(self, db: Session, download_start: datetime = None):
        """Update database entry to progress."""
        with self.lock:
            self.status = str(EDownloadStatus.IN_PROGRESS)
            self.download_start = download_start or datetime.now()
            self.download_stop = None
            self.status_fail_message = None
            db.commit()
            db.refresh(self)

    def failed(self, db: Session, status_fail_message: str, download_stop: datetime = None):
        """Update database entry to failed."""
        with self.lock:
            self.status = str(EDownloadStatus.FAILED)
            self.download_stop = download_stop or datetime.now()
            self.status_fail_message = status_fail_message
            db.commit()
            db.refresh(self)

    def done(self, db: Session, download_stop: datetime = None):
        """Update database entry to done."""
        with self.lock:
            self.status = str(EDownloadStatus.DONE)
            self.download_stop = download_stop or datetime.now()
            self.status_fail_message = None
            db.commit()
            db.refresh(self)

    #######################
    # DATABASE OPERATIONS #
    #######################

    @classmethod
    def get(cls, db: Session, name: str | Column[str], raise_if_missing=True):
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
    def get_if_exists(cls, *args, **kwargs):
        """Get single entry by name if it exists, else None"""
        return cls.get(*args, **kwargs, raise_if_missing=False)

    @classmethod
    def create(
        cls,
        db: Session,
        **kwargs,
    ):
        """Create and return entry"""
        entry = cls(**kwargs)
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry
