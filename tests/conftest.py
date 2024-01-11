"""
https://docs.pytest.org/en/6.2.x/fixture.html#conftest-py-sharing-fixtures-across-multiple-files

The conftest.py file serves as a means of providing fixtures for an entire directory.
Fixtures defined in a conftest.py can be used by any test in that package without needing to import them
(pytest will automatically discover them).
"""

# pylint: disable=wrong-import-position, wrong-import-order
# flake8: noqa

# isort: off
# First thing: don't automatically open database session.
# We'll do it in a pytest fixture and check it status.
import rs_server

rs_server.OPEN_DB_SESSION = False
# isort: on

import os
import os.path as osp

import pytest
import sqlalchemy
from dotenv import load_dotenv

from rs_server.db.database import sessionmanager
from services.common.rs_server_common.utils.logging import Logging

# Try to kill the existing postgres docker container if it exists
# and prune docker networks to clean the IPv4 address pool
os.system(
    """
docker rm -f $(docker ps -aqf name=postgres_rspy-pytest) >/dev/null 2>&1
docker network prune -f >/dev/null 2>&1
""",
)


@pytest.fixture(scope="session", autouse=True)
def read_cli(request):
    """Read pytest command-line options passed by the user"""

    # Use the minimal log level
    option = request.config.getoption("--log-cli-level", None) or request.config.getoption("--log-level", None)
    if option:
        Logging.level = option.upper()


@pytest.fixture(scope="session", name="docker_compose_file")
def docker_compose_file_(pytestconfig):
    """Return the path to the docker-compose.yml file to run before tests."""
    return osp.join(str(pytestconfig.rootdir), "tests", "resources", "db", "docker-compose.yml")


@pytest.fixture(scope="session")
def database(docker_ip, docker_services, docker_compose_file):  # pylint: disable=unused-argument
    """
    Init database connection from the docker-compose.yml file.
    docker_ip, docker_services are used by pytest-docker that runs docker compose.

    In case of error:
    `Bind for 0.0.0.0:5432 failed: port is already allocated`

    Run this to remove all postgres docker containers:
    `docker rm -f $(docker ps -aqf name=postgres_rspy-pytest)`

    Then you can also try:
    `docker system prune`
    """

    # Read the .env file that comes with docker-compose.yml
    load_dotenv(osp.join(osp.dirname(docker_compose_file), ".env"))

    # Check if database connection is OK
    def try_init() -> bool:
        try:
            # Open session
            sessionmanager.open_session()

            # Drop/create all database tables
            sessionmanager.drop_all()
            sessionmanager.create_all()

            return True

        except (ConnectionError, sqlalchemy.exc.OperationalError):
            return False

    # Try to init database until OK
    docker_services.wait_until_responsive(timeout=30, pause=3, check=try_init)

    # TODO: open a new database session for each test ?
    # See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
