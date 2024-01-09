"""
https://docs.pytest.org/en/6.2.x/fixture.html#conftest-py-sharing-fixtures-across-multiple-files

The conftest.py file serves as a means of providing fixtures for an entire directory.
Fixtures defined in a conftest.py can be used by any test in that package without needing to import them
(pytest will automatically discover them).
"""

import os.path as osp
import time
import timeit

import pytest
import sqlalchemy
from dotenv import load_dotenv
from rs_server_common.utils.logging import Logging

from rs_server.db.database import sessionmanager


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
async def database(docker_ip, docker_services, docker_compose_file):
    """
    Init database connection from the docker-compose.yml file.
    docker_ip, docker_services are used by pytest-docker that runs docker compose.

    In case of error:
    `Bind for 0.0.0.0:5432 failed: port is already allocated`

    Run this to remove all postgres docker containers:
    `docker rm -f $(docker ps -aqf name=postgres)`

    Then you can also try:
    `docker system prune`
    """

    # Read the .env file that comes with docker-compose.yml
    load_dotenv(osp.join(osp.dirname(docker_compose_file), ".env"))

    # Check if database connection is OK
    async def try_init() -> Exception | None:
        try:
            # Open session
            await sessionmanager.open_session()

            # Drop/create all database tables
            async with sessionmanager.connect() as connection:
                await sessionmanager.drop_all(connection)
                await sessionmanager.create_all(connection)

            # All is OK
            return None

        except ConnectionError as exception:
            return exception
        except sqlalchemy.exc.OperationalError as exception:
            return exception

    # Try to init database until OK
    await wait_until_responsive_async(timeout=30, pause=3, check=try_init)

    # TODO: open a new database session for each test ?
    # See: https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html


async def wait_until_responsive_async(check, timeout, pause, clock=timeit.default_timer):
    """
    Wait until a service is responsive.

    async reimplementation from docker_services.wait_until_responsive.
    """

    exception = None
    ref = clock()
    now = ref
    while (now - ref) < timeout:
        exception = await check()
        if exception is None:
            return
        time.sleep(pause)
        now = clock()

    raise RuntimeError("Timeout reached while waiting on service!") from exception
