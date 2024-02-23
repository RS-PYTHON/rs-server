"""Init the FastAPI application."""

import time
import typing
from contextlib import asynccontextmanager
from os import environ as env
from typing import Callable

import httpx
import sqlalchemy
from fastapi import APIRouter, FastAPI
from rs_server_common import depends
from rs_server_common.db.database import sessionmanager
from rs_server_common.schemas.health_schema import HealthSchema
from rs_server_common.utils.logging import Logging

# Add some endpoints specific to the main application
others_router = APIRouter(tags=["Others"])


# include_in_schema=False: hide this endpoint from the swagger
@others_router.get("/", include_in_schema=False)
async def home():
    """Home endpoint."""
    return {"message": "RS server home endpoint"}


# include_in_schema=False: hide this endpoint from the swagger
@others_router.get("/health", response_model=HealthSchema, name="Check service health", include_in_schema=False)
async def health() -> HealthSchema:
    """
    Always return a flag set to 'true' when the service is up and running.
    \f
    Otherwise this code won't be run anyway and the caller will have other sorts of errors.
    """
    return HealthSchema(healthy=True)


@typing.no_type_check
def init_app(
    routers: list[APIRouter],
    init_db: bool = True,
    pause: int = 3,
    timeout: int = None,
    startup_events: list[Callable] = None,
    shutdown_events: list[Callable] = None,
):  # pylint: disable=too-many-arguments
    """
    Init the FastAPI application.
    See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html

    Args:
        routers (list[APIRouter]): list of FastAPI routers to add to the application.
        init_db (bool): should we init the database session ?
        timeout (int): timeout in seconds to wait for the database connection.
        pause (int): pause in seconds to wait for the database connection.
        startup_events (list[Callable]): list of functions that should be run before the application starts
        shutdown_events (list[Callable]): list of functions that should be run when the application is shutting down
    """

    logger = Logging.default(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Automatically executed when starting and stopping the FastAPI server."""

        ###########
        # STARTUP #
        ###########

        # Open database session. Loop until the connection works.
        if app.state.init_db:
            db_info = f"'{env['POSTGRES_USER']}@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}'"
            while True:
                try:
                    sessionmanager.open_session()
                    logger.info(f"Reached {env['POSTGRES_DB']!r} database on {db_info}")
                    break
                except sqlalchemy.exc.OperationalError:
                    logger.warning(f"Trying to reach {env['POSTGRES_DB']!r} database on {db_info}")

                    # Sleep for n seconds and raise exception if timeout is reached.
                    if app.state.pg_timeout is not None:
                        app.state.pg_timeout -= app.state.pg_pause
                        if app.state.pg_timeout < 0:
                            raise
                    time.sleep(app.state.pg_pause)

        # Init objects for dependency injection
        depends.http_client = httpx.AsyncClient()

        # Call additional startup events
        for event in app.state.startup_events:
            event()

        yield

        ############
        # SHUTDOWN #
        ############

        # Call additional shutdown events
        for event in app.state.shutdown_events:
            event()

        # Close objects for dependency injection
        depends.http_client.aclose()
        depends.http_client = None

        # Close database session
        if app.state.init_db:
            try:
                await sessionmanager.close()
            except TypeError:  # TypeError: object NoneType can't be used in 'await' expression
                sessionmanager.close()

    # Override the swagger /docs URL from an environment variable.
    # Also set the openapi.json URL under the same path.
    try:
        docs_url = env["RSPY_DOCS_URL"].strip("/")
        docs_params = {"docs_url": f"/{docs_url}", "openapi_url": f"/{docs_url}/openapi.json"}
    except KeyError:
        docs_params = {}

    # Init the FastAPI application
    app = FastAPI(title="RS FastAPI server", lifespan=lifespan, **docs_params)

    # Pass arguments to the app so they can be used in the lifespan function above.
    app.state.init_db = init_db
    app.state.pg_pause = pause
    app.state.pg_timeout = timeout
    app.state.startup_events = startup_events or []
    app.state.shutdown_events = shutdown_events or []

    # Add routers to the FastAPI app
    for router in routers + [others_router]:
        app.include_router(router)

    return app
