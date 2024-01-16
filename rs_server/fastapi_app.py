"""Init the FastAPI application."""

import time
import typing
from contextlib import asynccontextmanager
from os import environ as env

import sqlalchemy
from fastapi import FastAPI
from rs_server_common.utils.logging import Logging

from rs_server.ADGS.api import adgs_search
from rs_server.CADIP.api import cadu_download, cadu_search, cadu_status
from rs_server.db.database import sessionmanager


@typing.no_type_check
def init_app(init_db=True, pause=3, timeout=None):
    """
    Init the FastAPI application.
    See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html

    :param int timeout: timeout in seconds to wait for the database connection.
    :param int pause: pause in seconds to wait for the database connection.
    """

    logger = Logging.default(__name__)

    lifespan = None

    if init_db:

        @asynccontextmanager
        async def lifespan(app: FastAPI):  # pylint: disable=function-redefined # noqa
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

                    # Sleep for n seconds and raise exception if timeout is reached.
                    if app.pg_timeout is not None:
                        app.pg_timeout -= app.pg_pause
                        if app.pg_timeout < 0:
                            raise
                    time.sleep(app.pg_pause)

            yield

            ############
            # STOPPING #
            ############

            # Close database session
            try:
                await sessionmanager.close()
            except TypeError:  # TypeError: object NoneType can't be used in 'await' expression
                sessionmanager.close()

    app = FastAPI(title="RS FastAPI server", lifespan=lifespan)

    # Pass postgres arguments to the app (maybe there is a cleaner way to do this)
    app.pg_pause = pause
    app.pg_timeout = timeout

    app.include_router(cadu_download.router)
    app.include_router(cadu_search.router)
    app.include_router(cadu_status.router)
    app.include_router(adgs_search.router)

    @app.get("/")
    async def home():
        """Home endpoint."""
        return {"message": "RS server home endpoint"}

    return app
