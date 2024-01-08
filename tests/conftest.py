"""
https://docs.pytest.org/en/6.2.x/fixture.html#conftest-py-sharing-fixtures-across-multiple-files

The conftest.py file serves as a means of providing fixtures for an entire directory.
Fixtures defined in a conftest.py can be used by any test in that package without needing to import them
(pytest will automatically discover them).
"""

import os.path as osp

import pytest
import sqlalchemy
from dotenv import load_dotenv
from rs_server_common.utils.logging import Logging

from rs_server.db import startup


@pytest.fixture(scope="session", autouse=True)
def read_cli(request):
    """Read pytest command-line options passed by the user"""

    # Use the minimal log level
    option = request.config.getoption("--log-cli-level", None) or request.config.getoption("--log-level", None)
    if option:
        Logging.level = option.upper()


@pytest.fixture(scope="session")
def docker_compose_file(pytestconfig):
    """Return the path to the docker-compose.yml file to run before tests."""
    return osp.join(str(pytestconfig.rootdir), "tests", "resources", "db", "docker-compose.yml")


@pytest.fixture(scope="session")
def database(docker_ip, docker_services, docker_compose_file):
    """
    Init database connection from the docker-compose.yml file.
    docker_ip, docker_services are used by pytest-docker that runs docker compose.

    In case of error:
    `Bind for 0.0.0.0:5432 failed: port is already allocated`

    Run this to remove all postgres docker containers:
    `docker rm -f $(docker ps -aqf name=postgres)`
    """

    # Read the .env file that comes with docker-compose.yml
    load_dotenv(osp.join(osp.dirname(docker_compose_file), ".env"))

    # Try to init database until OK
    def try_init():
        try:
            startup.init()
            return True
        except sqlalchemy.exc.OperationalError as e:
            return False

    docker_services.wait_until_responsive(timeout=30, pause=3, check=lambda: try_init())
