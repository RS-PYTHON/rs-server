"""FastAPI"""

import time
from contextlib import asynccontextmanager
from os import environ as env

import sqlalchemy
from fastapi import FastAPI
from rs_server_common.utils.logging import Logging

from rs_server import OPEN_DB_SESSION
from rs_server.CADIP.api import cadu_download, cadu_list, cadu_status
from rs_server.db.database import sessionmanager


def init_app(init_db=True):
    """
    Init the FastAPI application.
    See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
    """

    logger = Logging.default(__name__)

    lifespan = None

    if init_db:

        @asynccontextmanager
        async def lifespan(_: FastAPI):
            """Automatically executed when starting and stopping the FastAPI server."""

            ############
            # STARTING #
            ############

            # Open database session. Loop until the connection works.
            db_info = f"'{env['POSTGRES_USER']}@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}'"
            while True:
                try:
                    sessionmanager.open_session()
                    logger.info(f"Reached {env['POSTGRES_DB']!r} database on {db_info}")
                    break
                except sqlalchemy.exc.OperationalError:
                    logger.warning(f"Trying to reach {env['POSTGRES_DB']!r} database on {db_info}")
                    time.sleep(3)

            yield

            ############
            # STOPPING #
            ############

            # Close database session
            await sessionmanager.close()

    app = FastAPI(title="RS FastAPI server", lifespan=lifespan)

    app.include_router(cadu_download.router)
    app.include_router(cadu_list.router)
    app.include_router(cadu_status.router)

    @app.get("/")
    async def home():
        """Home endpoint."""
        return {"message": "RS server home endpoint"}

    return app
