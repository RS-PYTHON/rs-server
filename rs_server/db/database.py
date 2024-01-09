"""
Database connection.

Taken from: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
"""


import contextlib
import os
from threading import Lock
from typing import AsyncIterator

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from starlette.exceptions import HTTPException as StarletteHTTPException

Base = declarative_base()


class DatabaseSessionManager:
    """Database session configuration."""

    lock = Lock()

    def __init__(self):
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker | None = None

    @classmethod
    def url(cls):
        try:
            return os.getenv(
                "POSTGRES_URL",
                "postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}".format(
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

    async def open_session(self, host: str = None):
        with self.lock:
            if (self._engine is None) or (self._sessionmaker is None):
                self._engine = create_async_engine(host or self.url(), poolclass=NullPool)
                self._sessionmaker = async_sessionmaker(autocommit=False, bind=self._engine)

                # Create all tables.
                # First we make sure that we've imported all our model modules.
                import rs_server.CADIP.models.cadu_download_status

                async with self._engine.begin() as connection:
                    await self.create_all(connection)

    async def close(self):
        if self._engine is None:
            raise Exception("DatabaseSessionManager is not initialized")
        await self._engine.dispose()
        self._engine = None
        self._sessionmaker = None

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        # Open session and create tables on first use.
        # TODO: do it elsewhere ?
        # I've followed https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
        # but it doesn't say how to open session from running the uvicorn app.
        await self.open_session()

        if self._engine is None:
            raise Exception("DatabaseSessionManager is not initialized")

        async with self._engine.begin() as connection:
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        # Open session and create tables on first use.
        # TODO: do it elsewhere ?
        # I've followed https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
        # but it doesn't say how to open session from running the uvicorn app.
        await self.open_session()

        if self._sessionmaker is None:
            raise Exception("DatabaseSessionManager is not initialized")

        session = self._sessionmaker()
        try:
            yield session
        except Exception as exception:
            try:
                await session.rollback()
            finally:
                pass
            if isinstance(exception, StarletteHTTPException):
                raise
            raise HTTPException(status_code=400, detail=repr(exception))
        finally:
            await session.close()

    async def create_all(self, connection: AsyncConnection):
        await connection.run_sync(Base.metadata.create_all)

    async def drop_all(self, connection: AsyncConnection):
        await connection.run_sync(Base.metadata.drop_all)


sessionmanager = DatabaseSessionManager()


async def get_db():
    async with sessionmanager.session() as session:
        yield session


# TODO: raise HttpException
