"""
https://docs.pytest.org/en/6.2.x/fixture.html#conftest-py-sharing-fixtures-across-multiple-files

The conftest.py file serves as a means of providing fixtures for an entire directory.
Fixtures defined in a conftest.py can be used by any test in that package without needing to import them
(pytest will automatically discover them).
"""

import os
import os.path as osp
from contextlib import ExitStack

import pytest
import sqlalchemy
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from pytest_postgresql import factories
from pytest_postgresql.janitor import DatabaseJanitor

from rs_server.db.database import get_db, sessionmanager
from rs_server.fastapi_app import init_app
from services.common.rs_server_common.utils.logging import Logging

RESOURCES_DIR = osp.realpath(osp.join(osp.dirname(__file__), "resources"))


@pytest.fixture(scope="session", autouse=True)
def read_cli(request):
    """Read pytest command-line options passed by the user"""

    # Use the minimal log level
    option = request.config.getoption("--log-cli-level", None) or request.config.getoption("--log-level", None)
    if option:
        Logging.level = option.upper()


# Init the FastAPI application and database
# See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html


@pytest.fixture(autouse=True)
def app():
    """Init the FastAPI application."""
    with ExitStack():
        yield init_app(init_db=False)


@pytest.fixture
def client(app):
    """Test the FastAPI application."""
    with TestClient(app) as client:
        yield client


# Read the .env environment variables file
load_dotenv(osp.join(RESOURCES_DIR, "db", ".env"))
test_db = factories.postgresql_proc(port=None, dbname=os.environ["POSTGRES_DB"])


@pytest.fixture(scope="session", autouse=True)
async def connection_test(test_db):
    """Open a postgres database session."""

    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ["POSTGRES_HOST"]
    port = os.environ["POSTGRES_PORT"]
    dbname = os.environ["POSTGRES_DB"]

    with DatabaseJanitor(user, host, port, dbname, test_db.version, password):
        url = f"postgresql+psycopg2://{user}:@{host}:{port}/{dbname}"
        sessionmanager.open_session(url=url)
        yield
        await sessionmanager.close()


@pytest.fixture(scope="function", autouse=True)
async def create_tables(connection_test):
    """Drop and create all tables."""
    async with sessionmanager.connect() as connection:
        await sessionmanager.drop_all(connection)
        await sessionmanager.create_all(connection)


@pytest.fixture(scope="function", autouse=True)
async def session_override(app, connection_test):
    """Override the default database session."""

    async def get_db_override():
        async with sessionmanager.session() as session:
            yield session

    app.dependency_overrides[get_db] = get_db_override
