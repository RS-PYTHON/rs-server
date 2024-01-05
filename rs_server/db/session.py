"""Database session implementation."""

import os.path as osp
from threading import Lock

from dotenv import load_dotenv
from fastapi import HTTPException
from rs_server_common.utils.logging import Logging
from sqlalchemy.ext.declarative import declarative_base
from starlette.exceptions import HTTPException as StarletteHTTPException

SessionLocal = None

lock = Lock()

Base = declarative_base()


def add_commit_refresh(db, instance):
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


############################
# For dependency injection #
############################


# Use manually with "with contextmanager(get_db)() as db:"
def get_db():
    # TODO: refactor this code
    with Lock():
        if SessionLocal is None:
            from rs_server.db import startup

            startup.init()

    db = SessionLocal()
    try:
        yield db
    except:
        Logging.default().warning(f"Exception caught, rollback database transactions")
        db.rollback()
        raise
    finally:
        db.close()


# Use manually with with contextmanager(reraise_http)() as db:
def reraise_http():
    """
    Re-raise any exception raised by an HTTP operation into an HTTPException
    so the message can be displayed on the web client.
    """
    try:
        yield

    # Do nothing if the raised exception is already an HTTP exception.
    # TODO: handle in get_db ?
    except Exception as exception:
        if isinstance(exception, StarletteHTTPException):
            raise
        raise HTTPException(status_code=400, detail=repr(exception))
