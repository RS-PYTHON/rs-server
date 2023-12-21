"""CADU Product model implementation."""

from sqlalchemy import Boolean, Column, Enum, Integer, String
from sqlalchemy.orm import relationship

from rs_server.db.models.download_status_model import DownloadStatusEnum
from rs_server.db.session import Base


class CaduProductModel(Base):
    """CADU Product model implementation."""

    __tablename__ = "cadu_product"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    download_status: DownloadStatusEnum = Column(Enum(DownloadStatusEnum), default=DownloadStatusEnum.FAILED)


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_active = Column(Boolean, default=True)

    items = relationship("ItemModel", back_populates="owner")
