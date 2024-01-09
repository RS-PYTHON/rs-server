"""
Database connection.

Taken from: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
"""


import contextlib
import os
from threading import Lock
from typing import Iterator

from fastapi import HTTPException
from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException as StarletteHTTPException

Base = declarative_base()


class DatabaseSessionManager:
    """Database session configuration."""

    lock = Lock()

    def __init__(self):
        self._engine: Engine | None = None
        self._sessionmaker: sessionmaker | None = None

    @classmethod
    def url(cls):
        try:
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

    def open_session(self, host: str = None):
        with self.lock:
            if (self._engine is None) or (self._sessionmaker is None):
                self._engine = create_engine(host or self.url(), poolclass=NullPool)
                self._sessionmaker = sessionmaker(autocommit=False, autoflush=False, bind=self._engine)

                try:
                    # Create all tables.
                    # First we make sure that we've imported all our model modules.
                    import rs_server.CADIP.models.cadu_download_status

                    with self._engine.begin() as connection:
                        self.create_all(connection)

                # It fails if the database is unreachable, but even in this case the engine and session are not None.
                # Set them to None so we will try to create all tables again on the next try.
                except Exception:
                    self.close()
                    raise

    def close(self):
        if self._engine is None:
            raise Exception("DatabaseSessionManager is not initialized")
        self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    @contextlib.contextmanager
    def connect(self) -> Iterator[Connection]:
        # Open session and create tables on first use.
        # TODO: do it elsewhere ?
        # I've followed https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
        # but it doesn't say how to open session from running the uvicorn app.
        self.open_session()

        if self._engine is None:
            raise Exception("DatabaseSessionManager is not initialized")

        with self._engine.begin() as connection:
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise

    @contextlib.contextmanager
    def session(self) -> Iterator[Session]:
        # Open session and create tables on first use.
        # TODO: do it elsewhere ?
        # I've followed https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
        # but it doesn't say how to open session from running the uvicorn app.
        self.open_session()

        if self._sessionmaker is None:
            raise Exception("DatabaseSessionManager is not initialized")

        session = self._sessionmaker()
        try:
            yield session
        except Exception as exception:
            try:
                session.rollback()
            finally:
                pass
            self.reraise_http_exception(exception)
        finally:
            session.close()

    def create_all(self, connection: Connection):
        Base.metadata.create_all(bind=self._engine)

    def drop_all(self, connection: Connection):
        Base.metadata.drop_all(bind=self._engine)

    @classmethod
    def reraise_http_exception(cls, exception: Exception):
        if isinstance(exception, StarletteHTTPException):
            raise
        raise HTTPException(status_code=400, detail=repr(exception))


sessionmanager = DatabaseSessionManager()


def get_db():
    try:
        with sessionmanager.session() as session:
            yield session
    except Exception as exception:
        DatabaseSessionManager.reraise_http_exception(exception)


# TODO: raise HttpException
