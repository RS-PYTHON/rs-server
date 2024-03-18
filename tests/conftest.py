"""
https://docs.pytest.org/en/6.2.x/fixture.html#conftest-py-sharing-fixtures-across-multiple-files

The conftest.py file serves as a means of providing fixtures for an entire directory.
Fixtures defined in a conftest.py can be used by any test in that package without needing to import them
(pytest will automatically discover them).
"""

import os
import os.path as osp
import subprocess  # nosec ignore security issue
from contextlib import ExitStack
from pathlib import Path

import pytest
import yaml
from attr import dataclass
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from rs_server_common.db.database import DatabaseSessionManager, get_db, sessionmanager
from rs_server_common.utils.logging import Logging

from tests.app import init_app

RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / "resources"

RSPY_LOCAL_MODE = "RSPY_LOCAL_MODE"

###############################
# READ COMMAND LINE ARGUMENTS #
###############################


@pytest.fixture(scope="session", autouse=True)
def read_cli(request):
    """Read pytest command-line options passed by the user"""

    # Use the minimal log level
    option = request.config.getoption("--log-cli-level", None) or request.config.getoption("--log-level", None)
    if option:
        Logging.level = option.upper()


#####################
# SETUP ENVIRONMENT #
#####################

# Resource folders specified from the parent directory of this current script
S3_RSC_FOLDER = osp.realpath(osp.join(osp.dirname(__file__), "resources", "s3"))


def export_aws_credentials():
    """Export AWS credentials as environment variables for testing purposes.

    This function sets the following environment variables with dummy values for AWS credentials:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_SECURITY_TOKEN
    - AWS_SESSION_TOKEN
    - AWS_DEFAULT_REGION

    Note: This function is intended for testing purposes only, and it should not be used in production.

    Returns:
        None

    Raises:
        None
    """
    with open(osp.join(S3_RSC_FOLDER, "s3.yml"), "r", encoding="utf-8") as f:
        s3_config = yaml.safe_load(f)
        os.environ.update(s3_config["s3"])


########################
# FASTAPI AND DATABASE #
########################

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


@dataclass
class Envs:
    """A simple class that contains dict-defined environment variables."""

    envs: dict


@pytest.fixture(name="fastapi_app")
def fastapi_app_(request, docker_ip, docker_services, docker_compose_file):  # pylint: disable=unused-argument
    """
    Init the FastAPI application and the database connection from the docker-compose.yml file.
    docker_ip, docker_services are used by pytest-docker that runs docker compose.
    """

    # Set environment variables passed by parametrization (if any)
    with pytest.MonkeyPatch.context() as mp:
        # Default values
        pytest_env = {RSPY_LOCAL_MODE: True}  # no cluster mode for pytests

        # Read parametrization
        try:
            pytest_env.update(request.param.envs)  # envs = Envs instance
        except AttributeError:
            pass

        # Update environment variables
        for env, value in pytest_env.items():
            mp.setenv(env, str(value))

        # Read the .env file that comes with docker-compose.yml
        load_dotenv(RESOURCES_FOLDER / "db" / ".env")

        # Run all routers for the pytests
        with ExitStack():
            yield init_app()


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


##################
# OTHER FIXTURES #
##################


@pytest.fixture(scope="module", name="a_product")
def a_product_fixture():
    """Fixture factory to build a dummy cadip/aux product.
    The structure of this fake product is similar for CADIP and ADGS.
    The cadip/aux product is configured from an id and a datetime-like str.

    :return: the factory function to build a cadip/aux product.
    """

    def build(id_: str, name: str, at_date: str):
        """Build a dummy cadip/adgs product.

        :param id_: the id of the product
        :param name: the name of the product
        :param at_date: the time of the product.
        :return: the cadip/ags product.
        """
        return {
            "Id": id_,
            "Name": name,
            "PublicationDate": at_date,
            "Size": "size_test_value",
            "SessionID": "session_id_test_value",
            "Retransfer": False,
            "FinalBlock": True,
            "EvictionDate": "eviction_date_test_value",
            "Channel": "Channel_test_value",
            "BlockNumber": "BlockNumber_test_value",
            "ContentDate": {
                "Start": "ContentDate_Start_test_value",
                "End": "ContentDate_End_test_value",
            },
            "ContentLength": "ContentLength_test_value",
        }

    return build


@pytest.fixture(name="expected_products")
def expected_products_fixture(a_product) -> list[dict]:
    """Fixture that gives the default products returned by cadip/adgs.

    :param a_product: factory fixture to build a cadip/adgs product
    :return: the cadip/adgs product list
    """
    return [
        a_product(
            "2b17b57d-fff4-4645-b539-91f305c27c69",
            "DCS_01_S1A_20170501121534062343_ch1_DSDB_00001.raw",
            "2021-02-16T12:00:00.000Z",
        ),
        a_product("some_id_2", "S1A.raw", "2023-02-16T12:00:00.000Z"),
        a_product("some_id_3", "S2L1C.raw", "2019-02-16T12:00:00.000Z"),
    ]
