"""Download status implementation."""

from contextlib import contextmanager
from enum import Enum

from fastapi import HTTPException
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import Session, relationship

from rs_server.db.session import Base, get_db


class DownloadStatusEnum(Enum):
    NOT_STARTED = 1
    IN_PROGRESS = 2
    FAILED = 3
    DONE = 4


# class DownloadStatusModel(Base):
#     __tablename__ = "download_status"

#     id = Column(Integer, primary_key=True, index=True)
#     description = Column(String, index=True)

#     @classmethod
#     def populate(cls):
#         """Populate database with initial values."""

#         # Get database session
#         with contextmanager(get_db)() as db:
#             # If table is empty, add static values
#             in_base = db.query(cls).all()
#             if not in_base:
#                 for enum_ in DownloadStatusEnum:
#                     db.add(cls(description=enum_.name))
#                 db.commit()

#             # Else check values
#             else:
#                 values_in_base = [(row.id, row.description) for row in in_base]
#                 values_in_enum = [(enum_.value, enum_.name) for enum_ in DownloadStatusEnum]
#                 if values_in_base != values_in_enum:
#                     raise RuntimeError(
#                         f"'download_status' SQL table values:\n{values_in_base}\nShould be:\n{values_in_enum}",
#                     )


class ItemModel(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("UserModel", back_populates="items")
