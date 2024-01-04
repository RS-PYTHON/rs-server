"""
https://docs.pytest.org/en/6.2.x/fixture.html#conftest-py-sharing-fixtures-across-multiple-files

The conftest.py file serves as a means of providing fixtures for an entire directory.
Fixtures defined in a conftest.py can be used by any test in that package without needing to import them
(pytest will automatically discover them).
"""

import os

import pytest
from rs_server_common.utils.logging import Logging


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
    return os.path.join(str(pytestconfig.rootdir), "tests", "resources", "db", "docker-compose.yml")
