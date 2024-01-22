"""
https://docs.pytest.org/en/6.2.x/fixture.html#conftest-py-sharing-fixtures-across-multiple-files

The conftest.py file serves as a means of providing fixtures for an entire directory.
Fixtures defined in a conftest.py can be used by any test in that package without needing to import them
(pytest will automatically discover them).
"""

import os.path as osp
import subprocess  # nosec ignore security issue
from contextlib import ExitStack
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from rs_server_common.utils.logging import Logging

from rs_server.db.database import DatabaseSessionManager, get_db, sessionmanager
from rs_server.fastapi_app import init_app

RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / "resources"


@pytest.fixture(scope="session", autouse=True)
def read_cli(request):
    """Read pytest command-line options passed by the user"""

    # Use the minimal log level
    option = request.config.getoption("--log-cli-level", None) or request.config.getoption("--log-level", None)
    if option:
        Logging.level = option.upper()


# Init the FastAPI application and database
# See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
# But I have error
#     pytest_postgresql.exceptions.ExecutableMissingException: Could not found /usr/lib/postgresql/14/bin/pg_ctl.
#     Is PostgreSQL server installed?
#     Alternatively pg_config installed might be from different version that postgresql-server.
# See commit bbc6290df7c92fd306908830cbade8975e1eea6c

# Clean before running.
# No security risks since this file is not released into production.
subprocess.run([RESOURCES_FOLDER / "clean.sh"], check=False, shell=False)  # nosec ignore security issue


@pytest.fixture(scope="session", name="docker_compose_file")
def docker_compose_file_():
    """Return the path to the docker-compose.yml file to run before tests."""
    return RESOURCES_FOLDER / "db" / "docker-compose.yml"


@pytest.fixture(autouse=True, name="fastapi_app")
def fastapi_app_(docker_ip, docker_services, docker_compose_file):  # pylint: disable=unused-argument
    """Init the FastAPI application and the database connection from the docker-compose.yml file.
    docker_ip, docker_services are used by pytest-docker that runs docker compose.
    """

    # Read the .env file that comes with docker-compose.yml
    load_dotenv(RESOURCES_FOLDER / "db" / ".env")

    with ExitStack():
        yield init_app(init_db=True, pause=3, timeout=6)


@pytest.fixture(name="client")
def client_(fastapi_app):
    """Test the FastAPI application, opens the database session."""
    with TestClient(fastapi_app) as client:
        yield client


@pytest.fixture(scope="function", autouse=True)
def create_tables(client):  # pylint: disable=unused-argument
    """Drop and create all tables."""
    sessionmanager.drop_all()
    sessionmanager.create_all()


@pytest.fixture(scope="function", autouse=True)
def session_override(client, fastapi_app):  # pylint: disable=unused-argument
    """Override the default database session"""

    # pylint: disable=duplicate-code
    # NOTE: don't understand why we must duplicate this code.
    def get_db_override():
        try:
            with sessionmanager.session() as session:
                yield session
        except Exception as exception:  # pylint: disable=broad-exception-caught
            DatabaseSessionManager.reraise_http_exception(exception)

    fastapi_app.dependency_overrides[get_db] = get_db_override
