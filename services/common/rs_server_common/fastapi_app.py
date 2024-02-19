"""Init the FastAPI application."""

import time
import typing
from contextlib import asynccontextmanager
from os import environ as env

import sqlalchemy
from fastapi import APIRouter, FastAPI
from rs_server_common.db.database import sessionmanager
from rs_server_common.schemas.health_schema import HealthSchema
from rs_server_common.utils.logging import Logging

# Add some endpoints specific to the main application
others_router = APIRouter(tags=["Others"])


@others_router.get("/", include_in_schema=False)
async def home():
    """Home endpoint."""
    return {"message": "RS server home endpoint"}


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
):
    """
    Init the FastAPI application.
    See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html

    Args:
        routers (list[APIRouter]): list of FastAPI routers to add to the application.
        init_db (bool): should we init the database session ?
        timeout (int): timeout in seconds to wait for the database connection.
        pause (int): pause in seconds to wait for the database connection.
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
                    if app.state.pg_timeout is not None:
                        app.state.pg_timeout -= app.state.pg_pause
                        if app.state.pg_timeout < 0:
                            raise
                    time.sleep(app.state.pg_pause)

            yield

            ############
            # STOPPING #
            ############

            # Close database session
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

    # Pass postgres arguments to the app so they can be used in the lifespan function above.
    app.state.pg_pause = pause
    app.state.pg_timeout = timeout

    # Add routers to the FastAPI app
    for router in routers + [others_router]:
        app.include_router(router)

    return app
