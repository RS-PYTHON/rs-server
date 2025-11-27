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
from importlib import reload

# We are in local mode (no cluster).
# Do this before any other imports.
# flake8: noqa
# pylint: disable=wrong-import-order,wrong-import-position
os.environ["RSPY_LOCAL_MODE"] = "1"
from rs_server_common import settings, stac_api_common

reload(settings)

import datetime
import json
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from rs_server_adgs import adgs_retriever, adgs_utils
from rs_server_cadip import cadip_retriever, cadip_utils
from rs_server_common.authentication import oauth2  # pylint: disable=ungrouped-imports
from rs_server_common.authentication.authentication_to_external import (
    S3ExternalAuthenticationConfig,
    StationExternalAuthenticationConfig,
)
from rs_server_common.data_retrieval.eodag_provider import CustomEODataAccessGateway
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import map_stac_platform
from rs_server_edrs import edrs_client, edrs_connector
from rs_server_edrs.api import edrs_endpoints
from rs_server_edrs.api.edrs_endpoints import MockPgstacEdrs
from rs_server_prip import prip_retriever, prip_utils

from tests.app import init_app

RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / "resources"
CADIP_SEARCH = RESOURCES_FOLDER / "endpoints" / "cadip_search.yaml"
ADGS_SEARCH = RESOURCES_FOLDER / "endpoints" / "adgs_search.yaml"
PRIP_SEARCH = RESOURCES_FOLDER / "endpoints" / "prip_search.yaml"
EDRS_SEARCH = RESOURCES_FOLDER / "endpoints" / "edrs_search_config.yaml"
os.environ["RSPY_CADIP_SEARCH_CONFIG"] = str(CADIP_SEARCH.absolute())
os.environ["RSPY_ADGS_SEARCH_CONFIG"] = str(ADGS_SEARCH.absolute())
os.environ["RSPY_PRIP_SEARCH_CONFIG"] = str(PRIP_SEARCH.absolute())
os.environ["RSPY_EDRS_COLLECTIONS_CONFIG"] = str(EDRS_SEARCH)

TOKEN_USERNAME = os.getenv("RSPY_TOKEN_USERNAME", "test")
TOKEN_PASSWORD = os.getenv("RSPY_TOKEN_PASSWORD", "test")
TOKEN_CLIENT_SECRET = os.getenv("RSPY_CLIENT_SECRET", "client_secret")
TOKEN_URL = os.getenv("RSPY_TOKEN_URL", "http://127.0.0.1:5000/oauth2/token")

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


###########
# FASTAPI #
###########


@pytest.fixture(name="fastapi_app")
def fastapi_app_(
    request,
    mocker,
    monkeypatch,
):
    """Init the FastAPI application"""

    # Mock cluster/local mode to enable or disable authentication.
    try:
        cluster_mode = not request.param["RSPY_LOCAL_MODE"]

    # By default, force local mode.
    # We use the cluster mode only for the authentication tests.
    except (AttributeError, KeyError):
        cluster_mode = False

    # Get the router prefix, if any
    try:
        router_prefix = request.param.get("router_prefix", "")
        monkeypatch.setenv("router_prefix", router_prefix)
    except AttributeError:
        router_prefix = ""

    # Patch the global variables. See: https://stackoverflow.com/a/69685866
    mocker.patch("rs_server_common.settings.LOCAL_MODE", new=not cluster_mode, autospec=False)
    mocker.patch("rs_server_common.settings.CLUSTER_MODE", new=cluster_mode, autospec=False)

    if router_prefix == "/edrs":

        async def fake_landing_page(self, request, **kwargs):  # pylint: disable=unused-argument
            return {"type": "Catalog", "links": [{"rel": "self", "href": str(request.url)}]}

        mocker.patch.object(MockPgstacEdrs, "landing_page", fake_landing_page, create=True)

        class FakeConnector:
            def __init__(self, *args, **kwargs):
                self.connected = False

            def connect(self):
                self.connected = True

            def close(self):
                self.connected = False

            def walk(self, path):
                if path == "S1A":
                    return [{"path": "/NOMINAL/S1A/DCS_1_1_dat", "type": "dir"}]
                if path == "S1A/DCS_1_1_dat":
                    return [{"path": "/NOMINAL/S1A/DCS_1_1_dat/ch_1", "type": "dir"}]
                if path == "S1A/DCS_1_1_dat/ch_1":
                    return [
                        {"path": "/NOMINAL/S1A/DCS_1_1_dat/ch_1/file_dsib.xml", "type": "file"},
                        {"path": "/NOMINAL/S1A/DCS_1_1_dat/ch_1/data.raw", "type": "file", "size": 10},
                    ]
                return []

            def read_file(self, path):
                if str(path).lower().endswith("_dsib.xml"):
                    return {
                        "DCSU_Session_Information_Block": {
                            "time_start": "2024-01-01T00:00:00Z",
                            "time_stop": "2024-01-01T01:00:00Z",
                            "time_created": "2024-01-01T01:00:00Z",
                        },
                    }
                return b""

        mocker.patch.object(edrs_client, "EDRSConnector", FakeConnector)
        mocker.patch.object(edrs_connector, "EDRSConnector", FakeConnector)
        mocker.patch.object(edrs_endpoints, "EDRSConnector", FakeConnector)
        mocker.patch.object(
            edrs_client,
            "load_station_config",
            lambda *args, **kwargs: {
                "host": "fake",
                "port": 21,
                "login": "user",
                "password": "pass",
                "ca_cert": "",
                "client_cert": "",
                "client_key": "",
            },
        )
        mocker.patch.object(
            edrs_endpoints,
            "load_station_config",
            lambda *args, **kwargs: {
                "host": "fake",
                "port": 21,
                "login": "user",
                "password": "pass",
                "ca_cert": "",
                "client_cert": "",
                "client_key": "",
            },
        )

    # Mock the oauth2 environment variables for the cluster mode
    if cluster_mode:
        monkeypatch.setenv("OIDC_ENDPOINT", "http://OIDC_ENDPOINT")
        monkeypatch.setenv("OIDC_REALM", "OIDC_REALM")
        monkeypatch.setenv("OIDC_CLIENT_ID", "OIDC_CLIENT_ID")
        monkeypatch.setenv("OIDC_CLIENT_SECRET", "OIDC_CLIENT_SECRET")
        monkeypatch.setenv("RSPY_COOKIE_SECRET", "RSPY_COOKIE_SECRET")

        # Reload the oauth2 module with the cluster info
        reload(oauth2)

    # Run all routers for the pytests
    with ExitStack():
        yield init_app(router_prefix)


@pytest.fixture(name="client")
def client_(fastapi_app: FastAPI):
    """Test the FastAPI application"""
    with TestClient(fastapi_app) as client:
        yield client


@pytest.fixture(autouse=True)
def workaround_fixture(client):  # pylint: disable=unused-argument
    """
    I need this or I have the error "function uses no fixture 'fastapi_app'", I can't understand why.
    """


##################
# OTHER FIXTURES #
##################


@pytest.fixture(scope="function", autouse=True)
def clear_caches():
    """Clear caches at the end of each test"""
    yield
    adgs_retriever.init_adgs_provider.cache_clear()
    adgs_utils.read_conf.cache_clear()
    prip_retriever.init_prip_provider.cache_clear()
    prip_utils.read_conf.cache_clear()
    cadip_retriever.init_cadip_provider.cache_clear()
    cadip_utils.read_conf.cache_clear()
    cadip_utils.cadip_stac_mapper.cache_clear()
    CustomEODataAccessGateway.create.cache_clear()
    map_stac_platform.cache_clear()
    stac_api_common.get_cadip_queryables.cache_clear()
    stac_api_common.get_adgs_queryables.cache_clear()


@pytest.fixture(scope="function")
def use_module_for_station_token(monkeypatch):
    """
    Mock the env var RSPY_USE_MODULE_FOR_STATION_TOKEN to True. This will trigger the
    usage of the internal token module  for getting the token and setting it to the eodag
    """
    monkeypatch.setenv("RSPY_USE_MODULE_FOR_STATION_TOKEN", True)
    reload(adgs_retriever)
    reload(prip_retriever)
    reload(cadip_retriever)

    yield

    # Restore default value = False at the end of the test function
    monkeypatch.setenv("RSPY_USE_MODULE_FOR_STATION_TOKEN", False)
    reload(adgs_retriever)
    reload(prip_retriever)
    reload(cadip_retriever)


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
            "SessionId": session_id,
            "Retransfer": False,
            "FinalBlock": True,
            "EvictionDate": "eviction_date_test_value",
            "Channel": "Channel_test_value",
            "BlockNumber": "BlockNumber_test_value",
            "ContentDate": {
                "Start": "1970-01-01T12:00:00Z",
                "End": "1970-01-01T12:00:00Z",
            },
            "ContentLength": "size_test_value",
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
        "AcquisitionId": "53186_A1",
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


@pytest.fixture(name="set_token_env_var")
def set_token_env_var_fixture(monkeypatch):
    """Fixture to set environment variables for simulating the mounting of
    the external station token secrets in kubernetes.

    This fixture sets a variety of environment variables related to token-based
    authentication for different services, allowing tests to be executed with
    the correct configurations in place.
    The enviornment variables set are managing 3 stations:
    - adgs (service auxip)
    - ins (service cadip)
    - mps (service cadip)

    Args:
        monkeypatch: Pytest utility for temporarily modifying environment variables.
    """
    envvars = {
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__AUTHORIZATION": "Basic test",
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__CLIENT__ID": "client_id",
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__CLIENT__SECRET": TOKEN_CLIENT_SECRET,
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__TOKEN__URL": "\
http://mockup-auxip-adgs.processing.svc.cluster.local:8080/oauth2/token",
        "RSPY__TOKEN__AUXIP__ADGS__SERVICE__URL": "http://mockup-auxip-adgs.processing.svc.cluster.local:8080",
        "RSPY__TOKEN__AUXIP__ADGS__DOMAIN": "mockup-auxip-adgs.processing.svc.cluster.local",
        "RSPY__TOKEN__AUXIP__ADGS__SERVICE__NAME": "auxip",
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__AUTH__TYPE": "oauth2",
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__GRANT__TYPE": "password",
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__PASSWORD": TOKEN_PASSWORD,
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__SCOPE": "",
        "RSPY__TOKEN__AUXIP__ADGS__AUTHENTICATION__USERNAME": TOKEN_USERNAME,
        "RSPY__TOKEN__AUXIP__ADGS__TRUSTEDDOMAINS": "[trusted.domain1.eu, trusted.domain2.eu]",
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__AUTHORIZATION": "Basic test",
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__CLIENT__ID": "client_id",
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__CLIENT__SECRET": TOKEN_CLIENT_SECRET,
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__TOKEN__URL": "\
http://mockup-cadip-ins.processing.svc.cluster.local:8080/oauth2/token",
        "RSPY__TOKEN__CADIP__INS__SERVICE__URL": "http://mockup-cadip-ins.processing.svc.cluster.local:8080",
        "RSPY__TOKEN__CADIP__INS__DOMAIN": "mockup-cadip-ins.processing.svc.cluster.local",
        "RSPY__TOKEN__CADIP__INS__SERVICE__NAME": "cadip",
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__AUTH__TYPE": "oauth2",
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__GRANT__TYPE": "password",
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__PASSWORD": TOKEN_PASSWORD,
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__SCOPE": "",
        "RSPY__TOKEN__CADIP__INS__AUTHENTICATION__USERNAME": TOKEN_USERNAME,
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__AUTHORIZATION": "Basic test",
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__CLIENT__ID": "client_id",
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__CLIENT__SECRET": TOKEN_CLIENT_SECRET,
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__TOKEN__URL": "\
http://http://mockup-cadip-mps.processing.svc.cluster.local:8080/oauth2/token",
        "RSPY__TOKEN__CADIP__MPS__SERVICE__URL": "http://mockup-cadip-mps.processing.svc.cluster.local:8080",
        "RSPY__TOKEN__CADIP__MPS__DOMAIN": "mockup-cadip-mps.processing.svc.cluster.local",
        "RSPY__TOKEN__CADIP__MPS__SERVICE__NAME": "cadip",
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__AUTH__TYPE": "oauth2",
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__GRANT__TYPE": "password",
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__PASSWORD": TOKEN_PASSWORD,
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__SCOPE": "",
        "RSPY__TOKEN__CADIP__MPS__AUTHENTICATION__USERNAME": TOKEN_USERNAME,
    }
    for key, val in envvars.items():
        monkeypatch.setenv(key, val)
    yield  # restore the environment


@pytest.fixture(name="expected_config_token_file")
def expected_config_token_file_fixture() -> dict:
    """Fixture that gives the default configuration file that is created
    by using the environment variables set through the mounting of token secrets (see set_token_env_var)
    This config files is managing 3 stations:
    - adgs (service auxip)
    - ins (service cadip)
    - mps (service cadip)


    Return: a dictionary that represents that data by reading the YAML file using yaml.safe_load()
    """
    return {
        "external_data_sources": {
            "adgs": {
                "authentication": {
                    "auth_type": "oauth2",
                    "authorization": "Basic test",
                    "client_id": "client_id",
                    "client_secret": TOKEN_CLIENT_SECRET,
                    "grant_type": "password",
                    "password": TOKEN_PASSWORD,
                    "scope": "",
                    "token_url": "http://mockup-auxip-adgs.processing.svc.cluster.local:8080/oauth2/token",
                    "username": TOKEN_USERNAME,
                },
                "domain": "mockup-auxip-adgs.processing.svc.cluster.local",
                "service": {
                    "name": "auxip",
                    "url": "http://mockup-auxip-adgs.processing.svc.cluster.local:8080",
                },
                "trusteddomains": [
                    "trusted.domain1.eu",
                    "trusted.domain2.eu",
                ],
            },
            "ins": {
                "authentication": {
                    "auth_type": "oauth2",
                    "authorization": "Basic test",
                    "client_id": "client_id",
                    "client_secret": TOKEN_CLIENT_SECRET,
                    "grant_type": "password",
                    "password": TOKEN_PASSWORD,
                    "scope": "",
                    "token_url": "http://mockup-cadip-ins.processing.svc.cluster.local:8080/oauth2/token",
                    "username": TOKEN_USERNAME,
                },
                "domain": "mockup-cadip-ins.processing.svc.cluster.local",
                "service": {
                    "name": "cadip",
                    "url": "http://mockup-cadip-ins.processing.svc.cluster.local:8080",
                },
            },
            "mps": {
                "authentication": {
                    "auth_type": "oauth2",
                    "authorization": "Basic test",
                    "client_id": "client_id",
                    "client_secret": TOKEN_CLIENT_SECRET,
                    "grant_type": "password",
                    "password": TOKEN_PASSWORD,
                    "scope": "",
                    "token_url": "http://http://mockup-cadip-mps.processing.svc.cluster.local:8080/oauth2/token",
                    "username": TOKEN_USERNAME,
                },
                "domain": "mockup-cadip-mps.processing.svc.cluster.local",
                "service": {
                    "name": "cadip",
                    "url": "http://mockup-cadip-mps.processing.svc.cluster.local:8080",
                },
            },
        },
    }


@pytest.fixture(name="get_external_auth_config")
def get_external_auth_config_fixture(station_id) -> StationExternalAuthenticationConfig:
    """Fixture to provide an StationExternalAuthenticationConfig instance based on station_id.

    This fixture creates and returns an StationExternalAuthenticationConfig object with
    predefined values based on the provided station_id.

    Args:
        station_id (str): The identifier for the station, determining the service name.

    Returns:
        StationExternalAuthenticationConfig: An instance with the configuration for the given station_id.
    """
    # Determine the service based on the station_id
    service = "auxip" if station_id == "adgs" else "cadip"
    # Return a configured StationExternalAuthenticationConfig object
    return StationExternalAuthenticationConfig(
        station_id=station_id,
        domain=f"mockup-{service}-{station_id}.processing.svc.cluster.local",
        service_name=service,
        service_url="http://127.0.0.1:6001",
        auth_type="oauth2",
        token_url=TOKEN_URL,
        grant_type="password",
        username=TOKEN_USERNAME,
        password=TOKEN_PASSWORD,
        client_id="client_id",
        client_secret=TOKEN_CLIENT_SECRET,
        scope="openid",
        authorization="Basic test",
    )


@pytest.fixture(name="get_s3_external_auth_config")
def get_s3_external_auth_config_fixture(station_id) -> StationExternalAuthenticationConfig:
    """Fixture to provide an S3ExternalAuthenticationConfig instance based on station_id.

    This fixture creates and returns an S3ExternalAuthenticationConfig object with
    predefined values based on the provided station_id.

    Args:
        station_id (str): The identifier for the station, determining the service name.

    Returns:
        StationExternalAuthenticationConfig: An instance with the configuration for the given station_id.
    """
    # Return a configured S3ExternalAuthenticationConfig object
    return S3ExternalAuthenticationConfig(  # nosec B106
        station_id=station_id,
        domain=f"mockup-s3-{station_id}.processing.svc.cluster.local",
        service_name="s3",
        service_url="http://127.0.0.1:6001",
        auth_type="s3",
        access_key="abcdef",
        secret_key="123456",
    )


@pytest.fixture(name="cadip_feature")
@lru_cache(maxsize=1)
def cadip_stac_feature():
    """Fixture used to verify the output of rs-server translation of cadip_pickup_response fixture."""
    cadip_feature_json = RESOURCES_FOLDER / "endpoints" / "cadip_feature.json"
    with open(cadip_feature_json, encoding="utf-8") as file:
        return json.loads(file.read())


@pytest.fixture(name="cadip_session_response")
@lru_cache(maxsize=1)
def cadip_session_pickup_response():
    """Fixture used to mock the response from CADIP data pickup-point."""
    cadip_response_json = RESOURCES_FOLDER / "endpoints" / "cadip_session_pickup_response.json"
    with open(cadip_response_json, encoding="utf-8") as file:
        return json.loads(file.read())


@pytest.fixture(name="cadip_session_response_10_items")
@lru_cache(maxsize=1)
def cadip_session_pickup_response_10_items():
    """Fixture used to mock the response from CADIP data pickup-point."""
    cadip_response_json = RESOURCES_FOLDER / "endpoints" / "cadip_session_pickup_response_10_items.json"
    with open(cadip_response_json, encoding="utf-8") as file:
        return json.loads(file.read())


@pytest.fixture(name="cadip_file_response")
@lru_cache(maxsize=1)
def cadip_file_pickup_response():
    """Fixture used to mock the response from CADIP data pickup-point."""
    cadip_response_json = RESOURCES_FOLDER / "endpoints" / "cadip_file_pickup_response.json"
    with open(cadip_response_json, encoding="utf-8") as file:
        return json.loads(file.read())


@pytest.fixture(name="adgs_feature")
@lru_cache(maxsize=1)
def adgs_stac_feature():
    """Fixture used to verify the output of rs-server translation of adgs_pickup_response fixture."""
    adgs_feature_json = RESOURCES_FOLDER / "endpoints" / "adgs_feature.json"
    with open(adgs_feature_json, encoding="utf-8") as file:
        return json.loads(file.read())


@pytest.fixture(name="adgs_response")
@lru_cache(maxsize=1)
def adgs_pickup_response():
    """Fixture used to mock the response from ADGS data pickup-point."""
    adgs_response_json = RESOURCES_FOLDER / "endpoints" / "adgs_pickup_response.json"
    with open(adgs_response_json, encoding="utf-8") as file:
        return json.loads(file.read())


@pytest.fixture(name="prip_feature")
@lru_cache(maxsize=1)
def prip_feature():
    """Expected STAC Item for PRIP mapping test."""
    data_json = RESOURCES_FOLDER / "endpoints" / "prip_feature.json"
    with open(data_json, encoding="utf-8") as f:
        return json.loads(f.read())


@pytest.fixture(name="prip_feature_no_geom")
@lru_cache(maxsize=1)
def prip_feature_no_geom():
    """Expected STAC Item for PRIP mapping test."""
    data_json = RESOURCES_FOLDER / "endpoints" / "prip_feature_no_geometry.json"
    with open(data_json, encoding="utf-8") as f:
        return json.loads(f.read())


@pytest.fixture(name="prip_response")
@lru_cache(maxsize=1)
def prip_pickup_response():
    """Mock PRIP OData pickup response used by the mapping test."""
    data_json = RESOURCES_FOLDER / "endpoints" / "prip_pickup_response.json"
    with open(data_json, encoding="utf-8") as f:
        return json.loads(f.read())


@pytest.fixture(name="mock_token_dict")
def get_mock_token_dict():
    """Setup a mock for the token dictionary"""
    return {
        "access_token": "P4JSuo3gfQxKo0gfbQTb7nDn5OkzWP3umdGvy7G3CcI",
        "expires_in": 3600,
        "access_token_creation_date": datetime.datetime.now(),
        "refresh_token": "fakeRefreshToken",
        "refresh_expires_in": 7200,
        "refresh_token_creation_date": datetime.datetime.now(),
        "token_type": "Bearer",
    }


@pytest.fixture(name="adgs_response_10_items")
@lru_cache(maxsize=1)
def adgs_pickup_response_10_items():
    """Fixture used to mock the response from ADGS data pickup-point."""
    adgs_response_json = RESOURCES_FOLDER / "endpoints" / "adgs_pickup_response_10_items.json"
    with open(adgs_response_json, encoding="utf-8") as file:
        return json.loads(file.read())
