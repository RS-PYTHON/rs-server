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

"""
Database connection.

Taken from: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
"""

import contextlib
import multiprocessing
import os
import traceback
from functools import wraps
from pathlib import Path
from threading import Lock
from typing import Iterator

from fastapi import HTTPException
from filelock import FileLock
from rs_server_common.db import Base
from rs_server_common.utils.logging import Logging
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

logger = Logging.default(__name__)


class DatabaseSessionManager:
    """Database session configuration."""

    lock = Lock()
    multiprocessing_lock = multiprocessing.Lock()

    def __init__(self):
        """Create a Database session configuration."""
        self._engine: Engine | None = None
        self._sessionmaker: sessionmaker | None = None

    @classmethod
    def url(cls):
        """Get database connection URL."""
        try:
            # pylint: disable=consider-using-f-string
            return os.getenv(
                "POSTGRES_URL",
                "postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}".format(
                    user=os.environ["POSTGRES_USER"],
                    password=os.environ["POSTGRES_PASSWORD"],
                    host=os.environ["POSTGRES_HOST"],
                    port=os.environ["POSTGRES_PORT"],
                    dbname=os.environ["POSTGRES_DB"],
                ),
            )
        except KeyError as key_error:
            raise KeyError(
                "The PostgreSQL environment variables are missing: "
                "POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB",
            ) from key_error

    def open_session(self, url: str = ""):
        """Open database session."""

        # If the 'self' object is used by several threads in the same process,
        # make sure to initialize the session only once.
        with DatabaseSessionManager.lock:
            if (self._engine is None) or (self._sessionmaker is None):
                self._engine = create_engine(url or self.url(), poolclass=NullPool, pool_pre_ping=True)
                self._sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=self._engine)

                try:
                    # Create all tables.
                    # Warning: this only works if the database table modules have been imported
                    # e.g. import rs_server_adgs.adgs_download_status
                    self.create_all()

                # It fails if the database is unreachable, but even in this case the engine and session are not None.
                # Set them to None so we will try to create all tables again on the next try.
                except Exception:
                    self.close()
                    raise

    def close(self):
        """Close database session."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        self._sessionmaker = None

    @contextlib.contextmanager
    def connect(self) -> Iterator[Connection]:
        """Open new database connection instance."""

        if self._engine is None:
            raise RuntimeError("DatabaseSessionManager is not initialized")

        with self._engine.begin() as connection:
            try:
                yield connection

            # In case of any exception, rollback connection and re-raise into HTTP exception
            except Exception as exception:  # pylint: disable=broad-exception-caught
                connection.rollback()
                self.reraise_http_exception(exception)

    @contextlib.contextmanager
    def session(self) -> Iterator[Session]:
        """Open new database session instance."""

        if self._sessionmaker is None:
            raise RuntimeError("DatabaseSessionManager is not initialized")

        session = self._sessionmaker()
        try:
            yield session

        # In case of any exception, rollback session and re-raise into HTTP exception
        except Exception as exception:  # pylint: disable=broad-exception-caught
            session.rollback()
            self.reraise_http_exception(exception)

        # Close session when deleting instance.
        finally:
            session.close()

    @staticmethod
    def __filelock(func):
        """Avoid concurrent writing to the database using a file locK."""

        @wraps(func)
        def with_filelock(*args, **kwargs):
            """Wrap the the call to 'func' inside the lock."""

            # Let's do this only if the RSPY_WORKING_DIR environment variable is defined.
            # Write a .lock file inside this directory.
            try:
                with FileLock(Path(os.environ["RSPY_WORKING_DIR"]) / f"{__name__}.lock"):
                    return func(*args, **kwargs)

            # Else just call the function without a lock
            except KeyError:
                return func(*args, **kwargs)

        return with_filelock

    @__filelock
    def create_all(self):
        """Create all database tables."""
        with DatabaseSessionManager.multiprocessing_lock:  # Handle concurrent table creation by different processes
            Base.metadata.create_all(bind=self._engine)

    @__filelock
    def drop_all(self):
        """Drop all database tables."""
        with DatabaseSessionManager.multiprocessing_lock:  # Handle concurrent table creation by different processes
            Base.metadata.drop_all(bind=self._engine)

    @classmethod
    def reraise_http_exception(cls, exception: Exception):
        """Re-raise all exceptions into HTTP exceptions."""

        # Raised exceptions are not always printed in the console, so do it manually with the stacktrace.
        logger.error(traceback.format_exc())

        if isinstance(exception, StarletteHTTPException):
            raise exception
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=repr(exception))


sessionmanager = DatabaseSessionManager()


def get_db():
    """Return a database session for FastAPI dependency injection."""
    try:
        with sessionmanager.session() as session:
            yield session

    # Re-raise all exceptions into HTTP exceptions
    except Exception as exception:  # pylint: disable=broad-exception-caught
        DatabaseSessionManager.reraise_http_exception(exception)
