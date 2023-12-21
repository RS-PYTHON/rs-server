"""Database session implementation."""

import logging
import os

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

# SQLite configuration
# SQLALCHEMY_DATABASE_URL = "sqlite:////tmp/sql_app.db"
# engine = create_engine(
#     SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
# )

# PostgreSQL configuration.
# Use postgresql+psycopg2://... ?
# See: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg2
user = os.environ["POSTGRES_USER"]
password = os.environ["POSTGRES_PASSWORD"]
host = os.environ["POSTGRES_HOST"]
port = os.environ["POSTGRES_PORT"]
dbname = os.environ["POSTGRES_DB"]
SQLALCHEMY_DATABASE_URL = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

engine = create_engine(SQLALCHEMY_DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def add_commit_refresh(db, instance):
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


############################
# For dependency injection #
############################


# Use manually with with contextmanager(get_db)() as db:
def get_db():
    db = SessionLocal()
    try:
        yield db
    except:
        logging.getLogger().warning(f"Exception caught, rollback database transactions")
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
    except Exception as exception:
        if isinstance(exception, StarletteHTTPException):
            raise
        raise HTTPException(status_code=400, detail=exception.__repr__())  # string representation of the exception
