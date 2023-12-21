"""Download status implementation."""

from contextlib import contextmanager
from enum import Enum

from fastapi import HTTPException
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlalchemy.orm import Session, relationship

from rs_server.db.session import Base


class DownloadStatus(Enum):
    NOT_STARTED = 1
    IN_PROGRESS = 2
    FAILED = 3
    DONE = 4
