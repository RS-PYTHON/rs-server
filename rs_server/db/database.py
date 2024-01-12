"""
Database connection.

Taken from: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
"""


import contextlib
import os
from threading import Lock
from typing import Iterator

from fastapi import HTTPException
from rs_server_common.utils.logging import Logging
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException as StarletteHTTPException

from rs_server.db import Base


class DatabaseSessionManager:
    """Database session configuration."""

    lock = Lock()

    def __init__(self):
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

    def open_session(self, host: str = ""):
        """Open database session."""

        with self.lock:
            if (self._engine is None) or (self._sessionmaker is None):
                self._engine = create_engine(host or self.url(), poolclass=NullPool)
                self._sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=self._engine)

                try:
                    # Create all tables.
                    # First we make sure that we've imported all our model modules.
                    # pylint: disable=unused-import, import-outside-toplevel
                    # flake8: noqa
                    import rs_server.CADIP.models.cadu_download_status

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
                try:
                    connection.rollback()
                finally:
                    pass
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
            try:
                session.rollback()
            finally:
                pass
            self.reraise_http_exception(exception)

        # Close session when deleting instance.
        finally:
            session.close()

    def create_all(self):
        """Create all database tables."""
        Base.metadata.create_all(bind=self._engine)

    def drop_all(self):
        """Drop all database tables."""
        Base.metadata.drop_all(bind=self._engine)

    @classmethod
    def reraise_http_exception(cls, exception: Exception):
        """Re-raise all exceptions into HTTP exceptions."""

        # Raised exceptions are not always printed in the console, so do it manually.
        Logging.default().error(repr(exception))

        if isinstance(exception, StarletteHTTPException):
            raise exception
        raise HTTPException(status_code=400, detail=repr(exception))


sessionmanager = DatabaseSessionManager()


def get_db():
    """Return a database session for FastAPI dependency injection."""
    try:
        with sessionmanager.session() as session:
            yield session

    # Re-raise all exceptions into HTTP exceptions
    except Exception as exception:  # pylint: disable=broad-exception-caught
        DatabaseSessionManager.reraise_http_exception(exception)


# TODO: raise HttpException
