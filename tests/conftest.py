# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from rs_server_common.db.database import DatabaseSessionManager, get_db, sessionmanager
from rs_server_common.utils.logging import Logging

from tests.app import init_app

RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / "resources"


##################
# INITIALISATION #
##################


@pytest.fixture(scope="session", autouse=True)
def before_and_after(session_mocker):
    """This function is called before and after all the pytests have started/ended."""

    ####################
    # Before all tests #
    ####################

    # Avoid errors:
    # Transient error StatusCode.UNAVAILABLE encountered while exporting metrics to localhost:4317, retrying in 1s
    session_mocker.patch(  # pylint: disable=protected-access
        "opentelemetry.exporter.otlp.proto.grpc.exporter.OTLPExporterMixin",
    )._export.return_value = True

    yield

    ###################
    # After all tests #
    ###################


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
    with open(RESOURCES_FOLDER / "s3" / "s3.yml", "r", encoding="utf-8") as f:
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


@pytest.fixture(name="fastapi_app")
def fastapi_app_(request, mocker, docker_ip, docker_services, docker_compose_file):  # pylint: disable=unused-argument
    """
    Init the FastAPI application and the database connection from the docker-compose.yml file.
    docker_ip, docker_services are used by pytest-docker that runs docker compose.
    """

    # Mock cluster/local mode to enable or disable authentication.
    try:
        cluster_mode = not request.param["RSPY_LOCAL_MODE"]

    # By default, force local mode.
    # We use the cluster mode only for the authentication tests.
    except (AttributeError, KeyError):
        cluster_mode = False

    # Patch the global variables. See: https://stackoverflow.com/a/69685866
    mocker.patch("rs_server_common.settings.LOCAL_MODE", new=not cluster_mode, autospec=False)
    mocker.patch("rs_server_common.settings.CLUSTER_MODE", new=cluster_mode, autospec=False)

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

    def build(id_: str, name: str, at_date: str, session_id: str):
        """Build a dummy cadip/adgs product.

        :param id_: the id of the product
        :param name: the name of the product
        :param at_date: the time of the product.
        :param session_id: the product session id to wich belongs
        :return: the cadip/ags product.
        """
        return {
            "Id": id_,
            "Name": name,
            "PublicationDate": at_date,
            "Size": "size_test_value",
            "SessionID": session_id,
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
            "session_id1",
        ),
        a_product("some_id_2", "S1A.raw", "2023-02-16T12:00:00.000Z", "session_id2"),
        a_product("some_id_3", "S2L1C.raw", "2019-02-16T12:00:00.000Z", "session_id3"),
    ]


def a_session_fixture(id_, at_date, satellite_idf):
    """
    Function used to build full body of OData response from /Sessions.
    """
    return {
        "Id": "726f387b-ad2d-3538-8834-95e3cf8894c6",
        "SessionId": id_,
        "NumChannels": 2,
        "PublicationDate": at_date,
        "Satellite": satellite_idf,
        "StationUnitId": "01",
        "DownlinkOrbit": 53186,
        "AcquisitionId": "53186_1",
        "AntennaId": "MSP21",
        "FrontEndId": "01",
        "Retransfer": False,
        "AntennaStatusOK": True,
        "FrontEndStatusOK": True,
        "PlannedDataStart": "2024-03-28T18:52:08.336Z",
        "PlannedDataStop": "2024-03-28T19:00:51.075Z",
        "DownlinkStart": "2024-03-28T18:52:08.000Z",
        "DownlinkStop": "2024-03-28T19:00:52.000Z",
        "DownlinkStatusOK": True,
        "DeliveryPushOK": True,
    }


def expected_sessions_builder_fixture(session_id, publication_date, satellite):
    """Function used to return a list of sessions."""
    if isinstance(session_id, str):
        return [a_session_fixture(session_id, publication_date, satellite)]
    return [a_session_fixture(sid, pubd, satid) for sid, pubd, satid in zip(session_id, publication_date, satellite)]
