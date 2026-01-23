# pylint: disable=too-many-lines

# Copyright 2023-2025 Airbus, CS Group
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

"""Unittests for rs-server search endpoints."""

import json
import os
import re
from copy import deepcopy
from urllib.parse import quote, unquote

import pytest
import requests
import responses
import yaml
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import ValidationError
from rs_server_adgs import adgs_utils
from rs_server_cadip import cadip_utils
from rs_server_cadip.cadip_utils import cadip_map_mission
from rs_server_common.data_retrieval.provider import CreateProviderFailed, Provider
from rs_server_common.utils.utils import map_auxip_prip_mission
from rs_server_common.utils.utils2 import read_response_error
from shapely.geometry import box
from shapely.wkt import loads as wkt_loads

from tests.app import ROUTER_PREFIX_AUXIP, ROUTER_PREFIX_CADIP, ROUTER_PREFIX_PRIP

# pylint: disable=too-few-public-methods, too-many-arguments, too-many-locals,
# pylint: disable=too-many-branches, too-many-lines, too-many-statements


class TestOperatorDefinedCollections:
    """Class used to group tests for operator-defined collections."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, code",
        [
            ("/cadip/collections/cadip_session_incomplete/items", status.HTTP_422_UNPROCESSABLE_CONTENT),
            ("/cadip/collections/cadip_session_incomplete_no_stop/items", status.HTTP_400_BAD_REQUEST),
            ("/cadip/collections/cadip_session_incomplete_no_start/items", status.HTTP_400_BAD_REQUEST),
            ("/auxip/collections/adgs_invalid_no_start/items", status.HTTP_400_BAD_REQUEST),
            ("/auxip/collections/adgs_invalid_no_stop/items", status.HTTP_400_BAD_REQUEST),
        ],
    )
    def test_invalid_defined_collections(
        self,
        client,
        endpoint,
        code,
    ):
        """Test cases with invalid defined collections requests send to /session endpoint"""
        assert client.get(endpoint).status_code == code


class TestConstellationMapping:
    """Class used to group tests for platform/constellation mapping."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "platform, constellation, short_name, serial_id",
        [
            ("sentinel-1a", None, "sentinel-1", "A"),
            ("sentinel-2b", None, "sentinel-2", "B"),
            ("sentinel-5p", None, "sentinel-5P", None),
            (None, "sentinel-1", "sentinel-1", None),
            (None, "sentinel-2", "sentinel-2", None),
            (None, "sentinel-5P", "sentinel-5P", None),
        ],
    )
    def test_valid_adgs_mapping(self, platform, constellation, short_name, serial_id):
        """Pytest with only valid inputs, output is verified."""
        assert map_auxip_prip_mission(platform, constellation) == (short_name, serial_id)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "platform, constellation",
        [
            ("sentinel-invalid", None),  # invalid platform
            (None, "sentinel-invalid"),  # invalid constellation
            ("sentinel-invalid", "sentinel-1"),  # invalid platform, valid constellation
            ("sentinel-1a", "sentinel-invalid"),  # valid platform, invalid constellation
            ("sentinel-1a", "sentinel-5p"),  # invalid relation between platform and const
        ],
    )
    def test_invalid_adgs_mapping(self, platform, constellation):
        """Pytest using only invalid inputs, output is not verified, function should raise exception."""
        with pytest.raises(HTTPException):
            map_auxip_prip_mission(platform, constellation)

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "platform, constellation, satellite",
        [
            ("sentinel-1a", None, "S1A"),
            ("sentinel-2b", None, "S2B"),
            ("sentinel-5p", None, "S5P"),
            # if both plaftorm and const are defined, priority is to get platform since it is more precise
            ("sentinel-2b", "sentinel-2", "S2B"),
            ("sentinel-1a", "sentinel-1", "S1A"),
            ("sentinel-5p", "sentinel-5P", "S5P"),
            (None, "sentinel-1", "S1A,S1B,S1C,S1D"),
            (None, "sentinel-2", "S2A,S2B,S2C"),
            (None, "sentinel-5P", "S5P"),
        ],
    )
    def test_valid_cadip_mapping(self, platform, constellation, satellite):
        """Pytest with only valid inputs, output is verified."""
        assert cadip_map_mission(platform, constellation) == satellite

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "platform, constellation",
        [
            ("sentinel-invalid", None),  # invalid platform
            ("sentinel-1a", "sentinel-invalid"),  # valid platform, invalid constellation
            ("sentinel-1a", "sentinel-5p"),  # invalid relation between platform and const
            ("sentinel-2a", "sentinel-1"),
        ],
    )
    def test_invalid_cadip_mapping(self, platform, constellation):
        """Pytest using only invalid inputs, output is not verified, function should raise exception."""
        with pytest.raises(HTTPException):
            cadip_map_mission(platform, constellation)


class TestLandingPagesEndpoints:
    """Class for landing page tests."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, collection_link",
        [
            (ROUTER_PREFIX_CADIP, "/cadip", "/cadip/collections"),
            (ROUTER_PREFIX_AUXIP, "/auxip", "/auxip/collections"),
            (ROUTER_PREFIX_PRIP, "/prip", "/prip/collections"),
        ],
        indirect=["fastapi_app"],
    )
    def test_local_landing_pages(self, client: TestClient, endpoint, collection_link):
        """
        Unit test for checking the structure and links of the landing page.

        This test verifies that the landing page at the specified endpoint
        returns a response of type 'Catalog' and includes the necessary links.
        It checks that:
        - The 'type' field in the response is 'Catalog'.
        - The response contains links.
        - At least one link with the 'rel' attribute set to 'data' points to the
        '/cadip/collections' endpoint.

        Args:
            client: The test client to send requests.
            endpoint: The endpoint to test, e.g., "/cadip".
            role: The role to use for authentication (not used directly in the test).

        """
        # Check for response type and links to /collections.
        response = client.get(endpoint).json()
        assert response["type"] == "Catalog"
        assert response["links"]
        # Check for data relationship and redirect to /collections.
        assert any(collection_link in link["href"] for link in response["links"] if link["rel"] == "data")

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, roles",
        [
            ("/cadip/collections", ["rs_cadip_landing_page", "rs_cadip_authTest_read"]),
            ("/auxip/collections", ["rs_auxip_landing_page", "rs_auxip_authTest_read"]),
            ("/prip/collections", ["rs_prip_landing_page", "rs_prip_authTest_read"]),
        ],
    )
    def test_cluster_landing_page_with_roles(self, client, mocker, endpoint, roles):
        """
        Unit test for validating the collections landing page response.

        This test checks the response of the collections landing page at the
        specified endpoint. It ensures that:
        - The response contains both 'links' and 'collections' as lists.
        - These lists are not empty.
        - At least one link includes a title matching the expected session.
        - At least one collection's type is 'Collection'.
        - At least one collection's ID matches the expected collection name.

        Args:
            client: The test client to send requests.
            mocker: The pytest-mock fixture for mocking.
            endpoint: The endpoint to test, e.g., "/cadip/collections".
            role: The role used to simulate access control.

        """
        # Mock clusterMode
        mocker.patch("rs_server_common.settings.LOCAL_MODE", new=False, autospec=False)

        # Mock the request.state object
        mock_request_state = mocker.MagicMock()
        # Set mock auth_roles, set accest to "authTest" collection
        mock_request_state.auth_roles = roles

        # Patch the part where request.state.auth_roles is accessed
        mocker.patch(
            "rs_server_cadip.api.cadip_search.Request.state",
            new_callable=mocker.PropertyMock,
            return_value=mock_request_state,
        )
        mocker.patch(
            "rs_server_adgs.api.adgs_search.Request.state",
            new_callable=mocker.PropertyMock,
            return_value=mock_request_state,
        )
        mocker.patch(
            "rs_server_prip.api.prip_search.Request.state",
            new_callable=mocker.PropertyMock,
            return_value=mock_request_state,
        )
        response = client.get(endpoint).json()
        # Check links and collections.
        assert isinstance(response["links"], list)
        assert isinstance(response["collections"], list)
        # Check if not empty
        assert response["collections"]
        # Check that collection type is correctly set.
        assert any("Collection" in collection["type"] for collection in response["collections"])
        # Check that collection name is correctly set.
        assert any("test_collection" in collection["id"] for collection in response["collections"])

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, roles, request_path",
        [
            ("/cadip/collections", ["rs_cadip_landing_page"], "rs_server_cadip.api.cadip_search.Request.state"),
            ("/auxip/collections", ["rs_auxip_landing_page"], "rs_server_adgs.api.adgs_search.Request.state"),
            ("/prip/collections", ["rs_prip_landing_page"], "rs_server_prip.api.prip_search.Request.state"),
        ],
    )
    def test_cluster_landing_page_without_roles(self, client, mocker, endpoint, roles, request_path):
        """Test verifies the behavior when no propper roles are available:
        - It ensures that the response returns empty lists for 'links' and
        'collections' when the request state has no propper roles.
        """
        # Mock clusterMode
        mocker.patch("rs_server_common.settings.LOCAL_MODE", new=False, autospec=False)
        # Disable patcher, set request state to empty (Simulating an apikey with no propper roles)
        # Note: we still need the landing_page rights
        mock_empty_roles = mocker.MagicMock()
        mock_empty_roles.auth_roles = roles
        mocker.patch(request_path, new_callable=mocker.PropertyMock, return_value=mock_empty_roles)

        # No collection should be returned
        empty_response = client.get(endpoint).json()
        assert empty_response["collections"] == []

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, local_config",
        [
            ("/cadip/collections", "RSPY_CADIP_SEARCH_CONFIG"),
            ("/auxip/collections", "RSPY_ADGS_SEARCH_CONFIG"),
            ("/prip/collections", "RSPY_PRIP_SEARCH_CONFIG"),
        ],
    )
    def test_local_landing_page(self, client, endpoint, local_config):
        """On local mode, /collections should return all defined collections."""
        response = client.get(endpoint).json()
        # On local mode, response should contain all local defined collections.
        with open(str(os.environ.get(local_config)), encoding="utf-8") as local_cfg:
            data = yaml.safe_load(local_cfg)
        # Iterate over each collection in the response
        for response_collection in response["collections"]:
            found = False  # Flag to track if the id is found in data['collections']

            # Loop through the local data collections
            for item in data["collections"]:
                # Check if the "id" key exists and matches
                if "id" in item and item["id"] == response_collection["id"]:
                    found = True  # id found, set the flag to True
                    break  # No need to continue checking other items, exit the loop

            # Assert True if found, otherwise False
            assert found, f"ID {response_collection['id']} not found in local collections"


class TestQueryablesEndpoints:
    """Class used to group tests for */queryables endpoints"""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, expected_queryables",
        [
            (ROUTER_PREFIX_CADIP, "/cadip/queryables", ["platform", "constellation"]),
            (ROUTER_PREFIX_AUXIP, "/auxip/queryables", ["product:type", "platform", "constellation"]),
            (ROUTER_PREFIX_PRIP, "/prip/queryables", ["product:type", "platform", "constellation"]),
        ],
        indirect=["fastapi_app"],
    )
    def test_general_queryables(self, client, endpoint, expected_queryables):
        """Endpoint to test all queryables."""
        resp = client.get(endpoint).json()
        assert resp["title"] == "STAC Queryables."
        assert set(expected_queryables).issubset(set(resp["properties"].keys()))

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, expected_queryables",
        [
            (ROUTER_PREFIX_CADIP, "/cadip/collections/cadip_session_by_satellite/queryables", []),
            (ROUTER_PREFIX_AUXIP, "/auxip/collections/adgs_by_platform/queryables", ["product:type"]),
            (ROUTER_PREFIX_PRIP, "/prip/collections/S1A_L0_IW_RAW/queryables", ["product:type"]),
        ],
        indirect=["fastapi_app"],
    )
    def test_collection_queryables(self, client, endpoint, expected_queryables):
        """Endpoint to test specific collection queryables."""
        resp = client.get(endpoint).json()
        assert set(expected_queryables).issubset(set(resp["properties"].keys()))


class TestModelValidationError:
    """Class used to group tests for error when validating."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint",
        [
            (ROUTER_PREFIX_CADIP, "/cadip/search?collections=cadip_session_by_id_list"),
            (ROUTER_PREFIX_CADIP, "/cadip/collections/cadip_session_by_id_list/items"),
            (ROUTER_PREFIX_CADIP, "/cadip/collections/cadip_session_by_id_list/items/S1A_20170501121534062343"),
        ],
        indirect=["fastapi_app"],
    )
    def test_cadip_validation_errors(self, client, mocker, endpoint):
        """Test used to mock a validation error on pydantic model, should return HTTP 422."""
        mocker.patch(
            "rs_server_cadip.api.cadip_search.process_session_search",
            side_effect=ValidationError.from_exception_data("Invalid data", line_errors=[]),
        )
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint",
        [
            (ROUTER_PREFIX_AUXIP, "/auxip/collections/adgs_by_platform/items"),
            (ROUTER_PREFIX_AUXIP, "/auxip/collections/adgs_by_platform/items/sessionId"),
        ],
        indirect=["fastapi_app"],
    )
    def test_adgs_validation_errors(self, client, mocker, endpoint):
        """Test used to mock a validation error on pydantic model, should return HTTP 422."""
        mocker.patch(
            "rs_server_adgs.api.adgs_search.process_product_search",
            side_effect=ValidationError.from_exception_data("Invalid data", line_errors=[]),
        )
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint",
        [
            (ROUTER_PREFIX_PRIP, "/prip/collections/S1A_L0_IW_RAW/items"),
            (ROUTER_PREFIX_PRIP, "/prip/collections/S1A_L0_IW_RAW/items/sessionId"),
        ],
        indirect=["fastapi_app"],
    )
    def test_prip_validation_errors(self, client, mocker, endpoint):
        """Test used to mock a validation error on pydantic model for PRIP, should return HTTP 422."""
        mocker.patch(
            "rs_server_prip.api.prip_search.process_product_search",
            side_effect=ValidationError.from_exception_data("Invalid data", line_errors=[]),
        )
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.unit
    def test_adgs_search_error(self, client, mocker):
        """Test ADGS process_product_search throwing errors"""
        mocker.patch("rs_server_adgs.adgs_retriever.init_adgs_provider", side_effect=CreateProviderFailed)
        response = client.get("/auxip/collections/adgs_by_platform/items")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {"code": "BadRequest", "description": "Bad station identifier: "}
        mocker.patch(
            "rs_server_adgs.adgs_retriever.init_adgs_provider",
            side_effect=requests.exceptions.ConnectionError,
        )
        response = client.get("/auxip/collections/adgs_by_platform/items")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"code": "ServiceUnavailable", "description": "Station ADGS connection error: "}
        mocker.patch("rs_server_adgs.adgs_retriever.init_adgs_provider", side_effect=Exception)
        response = client.get("/auxip/collections/adgs_by_platform/items")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"code": "ServiceUnavailable", "description": "General failure: "}

    @pytest.mark.unit
    def test_prip_search_error(self, client, mocker):
        """Test PRIP process_product_search/provider init throwing errors (mirrors ADGS semantics)."""

        # Bad station identifier -> 400
        mocker.patch("rs_server_prip.prip_retriever.init_prip_provider", side_effect=CreateProviderFailed)
        response = client.get("/prip/collections/S1A_L0_IW_RAW/items")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        # Keep expectations parallel to ADGS; if your message text differs slightly, relax this to a 'startswith' check
        assert response.json() == {"code": "BadRequest", "description": "Bad station identifier: "}

        # Station connection error -> 503
        mocker.patch(
            "rs_server_prip.prip_retriever.init_prip_provider",
            side_effect=requests.exceptions.ConnectionError,
        )
        response = client.get("/prip/collections/S1A_L0_IW_RAW/items")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"code": "ServiceUnavailable", "description": "Station PRIP connection error: "}

        # Generic failure -> 503
        mocker.patch("rs_server_prip.prip_retriever.init_prip_provider", side_effect=Exception)
        response = client.get("/prip/collections/S1A_L0_IW_RAW/items")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"code": "ServiceUnavailable", "description": "General failure: "}


class TestErrorWhileBuildUpCollection:
    """Class used to group tests for error when processing."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint",
        [
            (ROUTER_PREFIX_CADIP, "/cadip/search?collections=cadip_session_by_id_list"),
        ],
        indirect=["fastapi_app"],
    )
    def test_cadip_collection_creation_failure(self, client, mocker, endpoint):
        """Test used to generate a KeyError while Collection is created, should return HTTP 422."""
        mocker.patch("rs_server_cadip.api.cadip_search.process_session_search", side_effect=KeyError)
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint",
        [(ROUTER_PREFIX_AUXIP, "/auxip/search?collection=adgs_by_platform")],
        indirect=["fastapi_app"],
    )
    def test_adgs_collection_creation_failure(self, client, mocker, endpoint):
        """Test used to generate a KeyError while Collection is created, should return HTTP 422."""
        mocker.patch("rs_server_adgs.api.adgs_search.process_product_search", side_effect=KeyError)
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint",
        [
            (ROUTER_PREFIX_PRIP, "/prip/search?collection=S1A_L0_IW_RAW"),
        ],
        indirect=["fastapi_app"],
    )
    def test_prip_collection_creation_failure(self, client, mocker, endpoint):
        """Test used to generate a KeyError while Collection is created, should return HTTP 422."""
        mocker.patch("rs_server_prip.api.prip_search.process_product_search", side_effect=KeyError)
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestFeatureOdataStacMapping:
    """Class that group unittests for /*/collections/{collection_id}/items/{item_id} mapping from odata to stac."""

    def setup(self, selector, cadip_response, adgs_response):
        """Helper function used to select fixture ouput for pickup response"""
        if selector == "adgs":
            return adgs_response
        return cadip_response

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_CADIP], indirect=["fastapi_app"])
    def test_cadip_feature_mapping(
        self,
        client: TestClient,
        cadip_feature,
        cadip_session_response,
        cadip_file_response,
    ):
        """Test a cadip pickup response with 2 assets is correctly mapped to a stac Feature
        Visit conftest to view content of cadip_feature and cadip_response.
        """
        # Note: for /items/{item-id} top is always set to 1.
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312'"
            "&$orderby=PublicationDate desc&$top=1&$skip=0",
            json=cadip_session_response,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051312'&$top=1000&$skip=0",
            json=cadip_file_response,
            status=200,
        )
        response: Response = client.get("/cadip/collections/cadip_session_by_id/items/S1A_20200105072204051312")
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response.json() == cadip_feature, "Features don't match"
        assert response.headers.get("Content-Type") == "application/geo+json"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_CADIP], indirect=["fastapi_app"])
    def test_cadip_empty_feature_mapping(self, client, cadip_feature):
        """Test to verify the output of rs-server when pick-up point response is empty."""
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312'"
            "&$orderby=PublicationDate desc&$top=1&$skip=0",
            json={"value": []},
            status=200,
        )
        response = client.get("/cadip/collections/cadip_session_by_id/items/S1A_20200105072204051312")
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response.json() != cadip_feature, "Features doesn't match"
        assert response.json() == {
            "code": "NotFound",
            "description": "Cadip session 'S1A_20200105072204051312' not found.",
        }
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_AUXIP], indirect=["fastapi_app"])
    def test_adgs_feature_mapping(self, client: TestClient, adgs_feature, adgs_response):
        """Test mapping of an adgs reponse with expanded attributes"""
        responses.add(
            responses.GET,
            "http://127.0.0.1:5001/Products?$filter=contains(Name, "
            "'S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF') and Attributes/OData.CSC.StringAttribute"
            "/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'AUX_OBMEMC')"
            "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            json=adgs_response,
            status=200,
        )
        response: Response = client.get(
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items/S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
        )
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response.json() == adgs_feature, "Features don't match"
        assert response.headers.get("Content-Type") == "application/geo+json"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_AUXIP], indirect=["fastapi_app"])
    def test_adgs_empty_feature_mapping(self, client, adgs_feature):
        """Test to verify the output of rs-server when pick-up point response is empty."""
        responses.add(
            responses.GET,
            "http://127.0.0.1:5001/Products?$filter=contains(Name, 'S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411"
            "_0001.EOF') and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC."
            "StringAttribute/Value eq 'AUX_OBMEMC')&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            json={"value": []},
            status=200,
        )
        response = client.get(
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items/S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
        )
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response.json() != adgs_feature, "Features doesn't match"
        assert response.json() == {
            "code": "NotFound",
            "description": "AUXIP item 'S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF' not found.",
        }
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_PRIP], indirect=["fastapi_app"])
    def test_prip_feature_mapping(
        self,
        client: TestClient,
        prip_feature,
        prip_response,
    ):
        """Test mapping of an prip reponse with expanded attributes"""
        # Note: for /items/{item-id} top is always set to 1.
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Products?$filter=contains(Name, "
            "'ABCD') and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            json=prip_response,
            status=200,
        )
        response: Response = client.get("/prip/collections/S1A_L0_IW_RAW/items/ABCD")
        assert response.json() == prip_feature, "Features don't match"
        assert response.headers.get("Content-Type") == "application/geo+json"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_PRIP], indirect=["fastapi_app"])
    def test_prip_empty_feature_mapping(self, client: TestClient, prip_feature):
        """Test rs-server output when PRIP returns empty payload (mirrors ADGS empty test)."""
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Products?$filter=contains(Name, 'ABCD') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            json={"value": []},
            status=200,
        )
        response = client.get("/prip/collections/S1A_L0_IW_RAW/items/ABCD")
        assert response.json() != prip_feature, "Features doesn't match"
        assert response.json() == {
            "code": "NotFound",
            "description": "PRIP item 'ABCD' not found.",
        }
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, response_body",
        [
            (
                "/auxip/collections/INVALID_COLLECTION/items/S1A_OPER_MPL_ORBPRE_20210214T021411_.EOF",
                {"code": "NotFound", "description": "Unknown AUXIP collection: 'INVALID_COLLECTION'"},
            ),
            (
                "/cadip/collections/INVALID_COLLECTION/items/S1A_20200105072204051312",
                {"code": "NotFound", "description": "Unknown CADIP collection: 'INVALID_COLLECTION'"},
            ),
            (
                "/prip/collections/INVALID_COLLECTION/items/ABCD",
                {"code": "NotFound", "description": "Unknown PRIP collection: 'INVALID_COLLECTION'"},
            ),
        ],
    )
    def test_invalid_collection_mapping(self, client, endpoint, response_body):
        """Test to verify the output of rs-server when given item collection is invalid."""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == response_body

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize(
        "endpoint, odata_url, response_body",
        [
            (
                "/auxip/collections/s2_adgs2_AUX_OBMEMC/items/INVALID_ITEM",
                "http://127.0.0.1:5001/Products?$filter=contains(Name, 'INVALID_ITEM') and Attributes/OData.CSC."
                "StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq "
                "'AUX_OBMEMC')&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                {"code": "NotFound", "description": "AUXIP item 'INVALID_ITEM' not found."},
            ),
            (
                "/prip/collections/S1A_L0_IW_RAW/items/INVALID_ITEM",
                "http://127.0.0.1:5000/Products?$filter=contains(Name, 'INVALID_ITEM') and Attributes/OData.CSC."
                "StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq "
                "'IW_RAW__0N')&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                {"code": "NotFound", "description": "PRIP item 'INVALID_ITEM' not found."},
            ),
        ],
        ids=["auxip-invalid-item", "prip-invalid-item"],
    )
    def test_adgs_prip_invalid_item_mapping(self, client, endpoint, odata_url, response_body):
        """Test to verify the output of rs-server when given collection is valid and item is invalid."""
        responses.add(
            responses.GET,
            odata_url,
            json={"value": []},
            status=200,
        )
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == response_body

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize(
        "endpoint, odata_session_url, odata_file_url, response_body",
        [
            (
                "/cadip/collections/cadip_session_by_id/items/INVALID_ITEM",
                "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312'"
                "&$orderby=PublicationDate desc&$top=1&$skip=0",
                'http://127.0.0.1:5000/Files?$filter="SessionID eq S1A_20200105072204051312"&$top=20',
                {"code": "NotFound", "description": "Cadip session 'INVALID_ITEM' not found."},
            ),
        ],
    )
    def test_cadip_invalid_item_mapping(
        self,
        client,
        endpoint,
        odata_session_url,
        odata_file_url,
        response_body,
    ):
        """Test to verify the output of rs-server when given collection is valid and item is invalid."""
        # Collection URL is valid, returning items
        responses.add(
            responses.GET,
            odata_session_url,
            json={"value": []},
            status=200,
        )
        # Map assets also (CADIP makes 2 requests)
        responses.add(
            responses.GET,
            odata_file_url,
            json={"value": []},
            status=404,
        )
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == response_body

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_PRIP], indirect=["fastapi_app"])
    def test_prip_feature_mapping_no_geometry(
        self,
        client: TestClient,
        prip_feature_no_geom,
        prip_response,
    ):
        """Test mapping of an prip reponse with expanded attributes"""
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Products?$filter=contains(Name, "
            "'WITHOUT-GEOFOOTPRINT') and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            json={"value": [prip_response["value"][1]]},
            status=200,
        )
        response: Response = client.get("/prip/collections/S1A_L0_IW_RAW/items/WITHOUT-GEOFOOTPRINT")

        returned_feature = response.json()
        assert returned_feature == prip_feature_no_geom, "Features don't match"

        # geometry is None or missing → bbox should not be added
        assert returned_feature.get("geometry") is None, "Expected geometry to be None"

        assert "bbox" not in returned_feature, "Expected bbox to be absent when geometry is missing"


class TestFeatureCollectionOdataStacMapping:
    """Class that group unittests for /*/collections/{collection-id}/items mapping from odata to stac."""

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_CADIP], indirect=["fastapi_app"])
    def test_cadip_feature_collection_mapping(
        self,
        client: TestClient,
        cadip_feature,
        cadip_file_response,
        cadip_session_response,
    ):
        """Test a cadip pickup response with 2 assets is correctly mapped to a stac Feature
        Visit conftest to view content of cadip_feature and cadip_response.
        """
        # Mock pickup response and token validation
        # Note, for /items, top value is the one defined in collection.
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312'"
            "&$orderby=PublicationDate desc&$top=10&$skip=0",
            json=cadip_session_response,
            status=200,
        )
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051312'&$top=1000&$skip=0",
            json=cadip_file_response,
            status=200,
        )
        response: Response = client.get("/cadip/collections/cadip_session_by_id/items")
        items = response.json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert items["type"] == "FeatureCollection", "Type doesn't match"
        assert items["features"][0]["properties"] == cadip_feature["properties"], "properties doesn't match"
        assert items["features"][0]["assets"] == cadip_feature["assets"], "assets doesn't match"
        assert items["features"][0]["id"] == cadip_feature["id"], "id doesn't match"

        assert response.headers.get("Content-Type") == "application/geo+json"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_AUXIP], indirect=["fastapi_app"])
    def test_adgs_feature_collection_mapping(
        self,
        client: TestClient,
        adgs_feature,
        adgs_response,
    ):
        """Test mapping of an adgs reponse with expanded attributes"""
        responses.add(
            responses.GET,
            "http://127.0.0.1:5001/Products?$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq "
            "'productType' and att/OData.CSC.StringAttribute/Value eq 'AUX_OBMEMC')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
            json=adgs_response,
            status=200,
        )
        response: Response = client.get("/auxip/collections/s2_adgs2_AUX_OBMEMC/items")
        items = response.json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert items["type"] == "FeatureCollection", "Type doesn't match"
        assert items["features"][0]["properties"] == adgs_feature["properties"], "properties doesn't match"
        assert items["features"][0]["assets"] == adgs_feature["assets"], "assets doesn't match"
        assert items["features"][0]["id"] == adgs_feature["id"], "id doesn't match"
        assert response.headers.get("Content-Type") == "application/geo+json"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_PRIP], indirect=["fastapi_app"])
    def test_prip_feature_collection_mapping(
        self,
        client: TestClient,
        prip_feature,
        prip_response,
    ):
        """Test mapping of an prip reponse with expanded attributes"""
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Products?$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq "
            "'productType' and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
            json=prip_response,
            status=200,
        )
        response: Response = client.get("/prip/collections/S1A_L0_IW_RAW/items")
        items = response.json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert items["type"] == "FeatureCollection", "Type doesn't match"
        assert items["features"][0]["properties"] == prip_feature["properties"], "properties doesn't match"
        assert items["features"][0]["assets"] == prip_feature["assets"], "assets doesn't match"
        assert items["features"][0]["id"] == prip_feature["id"], "id doesn't match"
        assert response.headers.get("Content-Type") == "application/geo+json"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, odata, expected_code",
        [
            # Default case, cadip_session_by_satellite collection sets Satellite to S1A
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/collections/cadip_session_by_satellite/items",
                "http://127.0.0.1:5000/Sessions?$filter=Satellite eq 'S1A'&$orderby=PublicationDate "
                "desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            # by setting filter filter=id=S1A_20200105072204051312, apart from satellite eq S1A which is
            #  set by collection, also add SessionId eq S1A_20200105072204051312 to odata.
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/collections/cadip_session_by_satellite/items?filter=id=S1A_20200105072204051312",
                "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312' "
                "and Satellite eq 'S1A'&$orderby=PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            # set filter with id AND datetime, check that odata is updated, now with SessionId, Satellite and PB date.
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/collections/cadip_session_by_satellite/items?filter=id='S1A_20200105072204051312' AND datetime="
                "'2020-02-16T12:00:00.000Z'",
                "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312' and Satellite eq 'S1A'"
                " and PublicationDate eq 2020-02-16T12:00:00.000Z&$orderby=PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/collections/cadip_session_by_satellite/items?filter=cadip:retransfer=True",
                "http://127.0.0.1:5000/Sessions?$filter=Satellite eq 'S1A' "
                "and Retransfer eq True&$orderby=PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/collections/cadip_session_by_satellite/items?filter=cadip:retransfer=should_be_bool",
                "no_odata",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/collections/cadip_session_by_satellite/items?filter=cadip:num_channels=2",
                "http://127.0.0.1:5000/Sessions?$filter=Satellite eq 'S1A' and NumChannels eq 2&"
                "$orderby=PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            # By setting filter with a invalid value (not withing queryables), should result in a 422
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/collections/cadip_session_by_satellite/items?filter=invalid='x'",
                "No odata for this",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/collections/adgs_by_platform/items",
                "http://127.0.0.1:5000/Products?$filter=Attributes/OData.CSC."
                "StringAttribute/any(att:att/Name eq 'platformShortName' and att/OData.CSC.StringAttribute/Value"
                " eq 'SENTINEL-1')&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/collections/adgs_by_platform/items?filter=Name=AUX_PPA",
                "http://127.0.0.1:5000/Products?$filter=contains(Name, 'AUX_PPA') and Attributes/OData.CSC."
                "StringAttribute/any(att:att/Name eq 'platformShortName' and att/OData.CSC.StringAttribute/Value"
                " eq 'SENTINEL-1')&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/collections/adgs_by_platform/items?filter=Name=AUX_PPA AND published="
                "'2020-02-16T12:00:00.000Z'",
                "http://127.0.0.1:5000/Products?$filter=contains(Name, 'AUX_PPA') and PublicationDate eq "
                "2020-02-16T12:00:00.000Z and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq "
                "'platformShortName' and att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/collections/adgs_by_platform/items?filter=processing:facility='PDMC'",
                "http://127.0.0.1:5000/Products?$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name"
                " eq 'platformShortName' and att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1') and "
                "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'processingCenter' and "
                "att/OData.CSC.StringAttribute/Value eq 'PDMC')&$orderby=PublicationDate desc&$top=10"
                "&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/collections/adgs_by_platform/items?filter=invalid='x'",
                "No odata",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/collections/adgs_by_platform/items?filter=published=invalid_date_format2020",
                "No odata",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            ),
        ],
        indirect=["fastapi_app"],
        ids=[
            "cadip",
            "cadip_id",
            "cadip_id_and_dt",
            "cadip_retransfer",
            "cadip_retransfer_invalid",
            "cadip_numchans",
            "cadip_inv",
            "auxip",
            "auxip_name",
            "auxip_name_and_dt",
            "auxip_processing",
            "auxip_inv",
            "auxip_inv_dt",
        ],
    )
    @responses.activate
    def test_cadip_query_filter(self, client, endpoint, odata, expected_code):
        """Test used for joining default collections with additional queries from filter param."""
        responses.add(responses.GET, odata, json={"value": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == expected_code

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, response_body",
        [
            (
                "/auxip/collections/INVALID_COLLECTION/items",
                {"code": "NotFound", "description": "Unknown AUXIP collection: 'INVALID_COLLECTION'"},
            ),
            (
                "/prip/collections/INVALID_COLLECTION/items",
                {"code": "NotFound", "description": "Unknown PRIP collection: 'INVALID_COLLECTION'"},
            ),
            (
                "/cadip/collections/INVALID_COLLECTION/items",
                {"code": "NotFound", "description": "Unknown CADIP collection: 'INVALID_COLLECTION'"},
            ),
        ],
    )
    def test_feature_collection_not_found(self, client, endpoint, response_body):
        """Test with an invalid collection request, should raise 404."""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == response_body

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, odata",
        [
            (
                "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?bbox=100.0,0.0,105.0,1.0",
                "http://127.0.0.1:5001/Products?$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq "
                "'productType' and att/OData.CSC.StringAttribute/Value eq 'AUX_OBMEMC')&$orderby=PublicationDate "
                "desc&$top=10&$skip=0&$expand=Attributes",
            ),
            (
                "/cadip/collections/cadip_session_by_id/items?bbox=100.0,0.0,105.0,1.0",
                "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312'&$orderby="
                "PublicationDate desc&$top=10&$skip=0",
            ),
        ],
    )
    @responses.activate
    def test_valid_bbox_values_items(self, client: TestClient, endpoint: str, odata: str):
        """Test endpoint call with valid bbox (4 or 6 coordinates without brackets)"""
        responses.add(responses.GET, odata, json={"value": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, odata",
        [
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&bbox=100.0,0.0,105.0,1.0",
                "http://127.0.0.1:5000/Products?$orderby=PublicationDate%20desc&$top=10&$skip=0&$expand=Attributes",
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip_session_by_id&bbox=100.0,0.0,105.0,1.0",
                "http://127.0.0.1:5000/Sessions?$filter=SessionId%20eq%20'S1A_20200105072204051312'"
                "&$orderby=PublicationDate desc&$top=10&$skip=0",
            ),
        ],
        indirect=["fastapi_app"],
    )
    @responses.activate
    def test_valid_bbox_values_search(self, client: TestClient, endpoint: str, odata: str):
        """Test endpoint call with valid bbox (4 or 6 coordinates without brackets)"""
        responses.add(responses.GET, odata, json={"value": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?bbox=[100.0, 0.0, 105.0, 1.0]",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?bbox=0",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?bbox=0,0",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?bbox=0,0,0",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?bbox=0,0,0,1,1",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?bbox=0,0,0,1,1,1,1",
            "/cadip/collections/cadip_session_by_id/items?bbox=[100.0, 0.0, 105.0, 1.0]",
            "/cadip/collections/cadip_session_by_id/items?bbox=0",
            "/cadip/collections/cadip_session_by_id/items?bbox=0,0",
            "/cadip/collections/cadip_session_by_id/items?bbox=0,0,0",
            "/cadip/collections/cadip_session_by_id/items?bbox=0,0,0,1,1",
            "/cadip/collections/cadip_session_by_id/items?bbox=0,0,0,1,1,1,1",
        ],
    )
    def test_invalid_bbox_values_items(self, client: TestClient, endpoint: str):
        """Test endpoint call with invalid bbox (brackets, wrong coordinates count)"""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error: str = read_response_error(response)
        assert error, response.json()
        assert error.replace("400: ", "") in (
            "could not convert string to float: '[100.0'",
            "invalid bbox: [100.0, 0.0, 105.0, 1.0]",
            "BBox '0' must have 4 or 6 values.",
            "BBox '0,0' must have 4 or 6 values.",
            "BBox '0,0,0' must have 4 or 6 values.",
            "BBox '0,0,0,1,1' must have 4 or 6 values.",
            "BBox '0,0,0,1,1,1,1' must have 4 or 6 values.",
        ), error

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint",
        [
            (ROUTER_PREFIX_AUXIP, "/auxip/search?bbox=[100.0, 0.0, 105.0, 1.0]"),
            (ROUTER_PREFIX_AUXIP, "/auxip/search?bbox=0"),
            (ROUTER_PREFIX_AUXIP, "/auxip/search?bbox=0,0"),
            (ROUTER_PREFIX_AUXIP, "/auxip/search?bbox=0,0,0"),
            (ROUTER_PREFIX_AUXIP, "/auxip/search?bbox=0,0,0,1,1"),
            (ROUTER_PREFIX_AUXIP, "/auxip/search?bbox=0,0,0,1,1,1,1"),
            (ROUTER_PREFIX_CADIP, "/cadip/search?bbox=[100.0, 0.0, 105.0, 1.0]"),
            (ROUTER_PREFIX_CADIP, "/cadip/search?bbox=0"),
            (ROUTER_PREFIX_CADIP, "/cadip/search?bbox=0,0"),
            (ROUTER_PREFIX_CADIP, "/cadip/search?bbox=0,0,0"),
            (ROUTER_PREFIX_CADIP, "/cadip/search?bbox=0,0,0,1,1"),
            (ROUTER_PREFIX_CADIP, "/cadip/search?bbox=0,0,0,1,1,1,1"),
        ],
        indirect=["fastapi_app"],
    )
    def test_invalid_bbox_values_search(self, client: TestClient, endpoint: str):
        """Test endpoint call with invalid bbox (brackets, wrong coordinates count)"""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = read_response_error(response)
        assert error, response.json()
        assert error.replace("400: ", "") in (
            "could not convert string to float: '[100.0'",
            "invalid bbox: [100.0, 0.0, 105.0, 1.0]",
            "BBox '0' must have 4 or 6 values.",
            "BBox '0,0' must have 4 or 6 values.",
            "BBox '0,0,0' must have 4 or 6 values.",
            "BBox '0,0,0,1,1' must have 4 or 6 values.",
            "BBox '0,0,0,1,1,1,1' must have 4 or 6 values.",
        ), error

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit='invalid_value'",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit='-5'",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=0",
            "/prip/collections/S1A_L0_IW_RAW/items?limit='invalid_value'",
            "/prip/collections/S1A_L0_IW_RAW/items?limit='-5'",
            "/prip/collections/S1A_L0_IW_RAW/items?limit=0",
            "/cadip/collections/cadip_session_by_id/items?limit='invalid_value'",
            "/cadip/collections/cadip_session_by_id/items?limit='-5'",
            "/cadip/collections/cadip_session_by_id/items?limit=0",
        ],
    )
    def test_invalid_limit_values(self, client: TestClient, endpoint: str):
        """Test endpoint call with invalid limits (str, negative, 0)"""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert json.loads(response.json()["description"])["detail"][0]["msg"] in (
            "Input should be a valid integer, unable to parse string as an integer",
            "Input should be greater than 0",
        )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, odata",
        [
            (
                "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=10000000",
                "http://127.0.0.1:5001/Products?$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq "
                "'productType' and att/OData.CSC.StringAttribute/Value eq 'AUX_OBMEMC')&$orderby=PublicationDate "
                "desc&$top=9999&$skip=0&$expand=Attributes",
            ),
            (
                "/prip/collections/S1A_L0_IW_RAW/items?limit=10000000",
                "http://127.0.0.1:5000/Products?$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq "
                "'productType' and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')&$orderby=PublicationDate "
                "desc&$top=9999&$skip=0&$expand=Attributes",
            ),
            (
                "/cadip/collections/cadip_session_by_id/items?limit=10000000",
                "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312'&$orderby="
                "PublicationDate desc&$top=9999&$skip=0",
            ),
        ],
    )
    @responses.activate
    def test_bigger_limit_than_allowed(self, client, endpoint, odata):
        """
        Test that if user request with a limit value bigger than max allowed in config
        the limit value is set to max_allowed - 1.
        Limit in request is set to 1_000_000, for given collection max allowed is set to 10000, therefore
        in the final odata request, $top is set to 9999.
        """
        responses.add(responses.GET, odata, json={"value": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_200_OK

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=1&page='invalid'",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=1&page=-5",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=1&page='0'",
            "/prip/collections/S1A_L0_IW_RAW/items?limit=1&page='invalid'",
            "/prip/collections/S1A_L0_IW_RAW/items?limit=1&page=-5",
            "/prip/collections/S1A_L0_IW_RAW/items?limit=1&page='0'",
            "/cadip/collections/cadip_session_by_id/items?limit=1&page='invalid'",
            "/cadip/collections/cadip_session_by_id/items?limit=1&page=-5",
            "/cadip/collections/cadip_session_by_id/items?limit=1&page='0'",
        ],
    )
    def test_invalid_page_values(self, client, endpoint):
        """Test endpoint call with invalid pages (str, negative, 0)"""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "Invalid page value" in response.json()["description"]

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=1&page=1&sortby='invalid'",
            "/prip/collections/S1A_L0_IW_RAW/items?limit=1&page=1&sortby='invalid'",
            "/cadip/collections/cadip_session_by_id/items?limit=1&page=1&sortby='invalid'",
        ],
    )
    @responses.activate
    def test_invalid_sortby_values(self, client, endpoint):
        """Test endpoint call with invalid pages (str, negative, 0)"""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "parameter is not sortable" in response.json()["description"]

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, odata, expected_code",
        [
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=2018-02-12T23:20:50.888Z",
                "http://127.0.0.1:5000/Products?$filter=PublicationDate eq 2018-02-12T23:20:50.888Z"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=2018-02-12T23:20:50.000Z/2019-02-12T23:20:50.001Z",
                "http://127.0.0.1:5000/Products?$filter="
                "(PublicationDate gt 2018-02-12T23:20:50.000Z or PublicationDate eq 2018-02-12T23:20:50.000Z) and "
                "(PublicationDate lt 2019-02-12T23:20:50.001Z or PublicationDate eq 2019-02-12T23:20:50.001Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=2018-02-12T23:20:50Z/..",
                "http://127.0.0.1:5000/Products?$filter="
                "(PublicationDate gt 2018-02-12T23:20:50.000Z or PublicationDate eq 2018-02-12T23:20:50.000Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=../2018-02-12T23:20:50.001Z",
                "http://127.0.0.1:5000/Products?$filter="
                "(PublicationDate lt 2018-02-12T23:20:50.001Z or PublicationDate eq 2018-02-12T23:20:50.001Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (ROUTER_PREFIX_AUXIP, "/auxip/search?collections=adgs&datetime=../..", "x", status.HTTP_400_BAD_REQUEST),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=invalid/..",
                "x",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=../invalid",
                "x",
                status.HTTP_400_BAD_REQUEST,
            ),
            # datime without miliseconds
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=2018-02-12T23:20:50Z",
                "http://127.0.0.1:5000/Products?$filter=PublicationDate eq 2018-02-12T23:20:50.000Z&$orderby="
                "PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_PRIP,
                "/prip/search?collections=prip&datetime=2018-02-12T23:20:50.888Z",
                "http://127.0.0.1:5000/Products?$filter=PublicationDate eq 2018-02-12T23:20:50.888Z"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_PRIP,
                "/prip/search?collections=prip&datetime=2018-02-12T23:20:50.000Z/2019-02-12T23:20:50.001Z",
                "http://127.0.0.1:5000/Products?$filter="
                "(PublicationDate gt 2018-02-12T23:20:50.000Z or PublicationDate eq 2018-02-12T23:20:50.000Z) and "
                "(PublicationDate lt 2019-02-12T23:20:50.001Z or PublicationDate eq 2019-02-12T23:20:50.001Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_PRIP,
                "/prip/search?collections=prip&datetime=2018-02-12T23:20:50Z/..",
                "http://127.0.0.1:5000/Products?$filter="
                "(PublicationDate gt 2018-02-12T23:20:50.000Z or PublicationDate eq 2018-02-12T23:20:50.000Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_PRIP,
                "/prip/search?collections=prip&datetime=../2018-02-12T23:20:50.001Z",
                "http://127.0.0.1:5000/Products?$filter="
                "(PublicationDate lt 2018-02-12T23:20:50.001Z or PublicationDate eq 2018-02-12T23:20:50.001Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (ROUTER_PREFIX_PRIP, "/prip/search?collections=prip&datetime=../..", "x", status.HTTP_400_BAD_REQUEST),
            (
                ROUTER_PREFIX_PRIP,
                "/prip/search?collections=prip&datetime=invalid/..",
                "x",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                ROUTER_PREFIX_PRIP,
                "/prip/search?collections=prip&datetime=../invalid",
                "x",
                status.HTTP_400_BAD_REQUEST,
            ),
            # datime without miliseconds
            (
                ROUTER_PREFIX_PRIP,
                "/prip/search?collections=prip&datetime=2018-02-12T23:20:50Z",
                "http://127.0.0.1:5000/Products?$filter=PublicationDate eq 2018-02-12T23:20:50.000Z&$orderby="
                "PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=2018-02-12T23:20:50.777Z",
                "http://127.0.0.1:5000/Sessions?$filter=PublicationDate eq 2018-02-12T23:20:50.777Z"
                "&$orderby=PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=2018-02-12T23:20:50Z/2019-02-12T23:20:50Z",
                "http://127.0.0.1:5000/Sessions?$filter="
                "(PublicationDate gt 2018-02-12T23:20:50.000Z or PublicationDate eq 2018-02-12T23:20:50.000Z) and "
                "(PublicationDate lt 2019-02-12T23:20:50.000Z or PublicationDate eq 2019-02-12T23:20:50.000Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=2018-02-12T23:20:50Z/..",
                "http://127.0.0.1:5000/Sessions?$filter="
                "(PublicationDate gt 2018-02-12T23:20:50.000Z or PublicationDate eq 2018-02-12T23:20:50.000Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=../2018-02-12T23:20:50Z",
                "http://127.0.0.1:5000/Sessions?$filter="
                "(PublicationDate lt 2018-02-12T23:20:50.000Z or PublicationDate eq 2018-02-12T23:20:50.000Z)"
                "&$orderby=PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
            (ROUTER_PREFIX_CADIP, "/cadip/search?collections=cadip&datetime=../..", "x", status.HTTP_400_BAD_REQUEST),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=invalid/..",
                "x",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=../invalid",
                "x",
                status.HTTP_400_BAD_REQUEST,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=2018-02-12T23:20:50Z",
                "http://127.0.0.1:5000/Sessions?$filter=PublicationDate eq 2018-02-12T23:20:50.000Z&$orderby="
                "PublicationDate desc&$top=10&$skip=0",
                status.HTTP_200_OK,
            ),
        ],
        indirect=["fastapi_app"],
        ids=[
            "adgs1",
            "adgs2",
            "adgs3",
            "adgs4",
            "adgs5",
            "adgs6",
            "adgs7",
            "adgs8",
            "prip1",
            "prip2",
            "prip3",
            "prip4",
            "prip5",
            "prip6",
            "prip7",
            "prip8",
            "cadip1",
            "cadip2",
            "cadip3",
            "cadip4",
            "cadip5",
            "cadip6",
            "cadip7",
            "cadip8",
        ],
    )
    @responses.activate
    def test_valid_datetime(self, client, endpoint, odata, expected_code):
        """Test used to group all combination of datetime values. Fixed, closed/open interval."""
        responses.add(responses.GET, odata, json={"value": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == expected_code

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, odata, expected_code",
        [
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_BEFORE(start_datetime, '2025-04-01T00:00:00Z')"
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/Start lt 2025-04-01T00:00:00.000Z)"
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_AFTER(start_datetime, '2025-04-01T00:00:00Z')"
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/Start gt 2025-04-01T00:00:00.000Z)"
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_MEETS(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/End eq 2025-04-01T00:00:00.000Z)"
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_METBY(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/Start eq 2025-04-02T00:00:00.000Z)"
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_OVERLAPS(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/Start lt 2025-04-01T00:00:00.000Z and 2025-04-01T00:00:00.000Z lt ContentDate/End and ContentDate/End lt 2025-04-02T00:00:00.000Z)"  # noqa: E501 # pylint: disable=line-too-long
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_OVERLAPPEDBY(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(2025-04-01T00:00:00.000Z lt ContentDate/Start and ContentDate/Start lt 2025-04-02T00:00:00.000Z and ContentDate/End gt 2025-04-02T00:00:00.000Z)"  # noqa: E501 # pylint: disable=line-too-long
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            # TODO enable these tests when pygeofilter supports these operators
            # (
            #    ROUTER_PREFIX_AUXIP,
            #    "/auxip/search?collections=adgs&filter="
            #    "T_STARTS(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
            #    "&sortby=-properties.created&limit=1",
            #    "http://127.0.0.1:5000/Products?$filter="
            #    "(ContentDate/Start eq 2025-04-01T00:00:00.000Z and ContentDate/End lt 2025-04-02T00:00:00.000Z)"
            #    "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            #    status.HTTP_200_OK,
            # ),
            # (
            #    ROUTER_PREFIX_AUXIP,
            #    "/auxip/search?collections=adgs&filter="
            #    "T_STARTEDBY(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
            #    "&sortby=-properties.created&limit=1",
            #    "http://127.0.0.1:5000/Products?$filter="
            #    "(ContentDate/Start eq 2025-04-01T00:00:00.000Z and ContentDate/End gt 2025-04-02T00:00:00.000Z)"
            #    "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            #    status.HTTP_200_OK,
            # ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_DURING(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/Start gt 2025-04-01T00:00:00.000Z and ContentDate/End lt 2025-04-02T00:00:00.000Z)"
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_CONTAINS(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/Start lt 2025-04-01T00:00:00.000Z and ContentDate/End gt 2025-04-02T00:00:00.000Z)"
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            # TODO enable these tests when pygeofilter supports these operators
            # (
            #    ROUTER_PREFIX_AUXIP,
            #    "/auxip/search?collections=adgs&filter="
            #    "T_FINISHES(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
            #    "&sortby=-properties.created&limit=1",
            #    "http://127.0.0.1:5000/Products?$filter="
            #    "(ContentDate/Start gt 2025-04-01T00:00:00.000Z and ContentDate/End eq 2025-04-02T00:00:00.000Z)"
            #    "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            #    status.HTTP_200_OK,
            # ),
            # (
            #    ROUTER_PREFIX_AUXIP,
            #    "/auxip/search?collections=adgs&filter="
            #    "T_FINISHEDBY(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
            #    "&sortby=-properties.created&limit=1",
            #    "http://127.0.0.1:5000/Products?$filter="
            #    "(ContentDate/Start lt 2025-04-01T00:00:00.000Z and ContentDate/End eq 2025-04-02T00:00:00.000Z)"
            #    "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            #    status.HTTP_200_OK,
            # ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_EQUALS(INTERVAL(start_datetime, end_datetime), INTERVAL('2025-04-01T00:00:00Z', '2025-04-02T00:00:00Z'))"  # noqa: E501 # pylint: disable=line-too-long
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/Start eq 2025-04-01T00:00:00.000Z and ContentDate/End eq 2025-04-02T00:00:00.000Z)"
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            # TODO enable these tests when pygeofilter supports these operators
            # (
            #    ROUTER_PREFIX_AUXIP,
            #    "/auxip/search?collections=adgs&filter="
            #    "T_DISJOINT(start_datetime, '2025-04-01T00:00:00Z')"
            #    "&sortby=-properties.created&limit=1",
            #    "http://127.0.0.1:5000/Products?$filter="
            #    "not (ContentDate/Start lte 2025-04-02T00:00:00.000Z and ContentDate/End gte 2025-04-01T00:00:00.000Z)"
            #    "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            #    status.HTTP_200_OK,
            # ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&filter="
                "T_INTERSECTS(start_datetime, '2025-04-01T00:00:00Z')"
                "&sortby=-properties.created&limit=1",
                "http://127.0.0.1:5000/Products?$filter="
                "(ContentDate/Start lte 2025-04-01T00:00:00.000Z and ContentDate/Start gte 2025-04-01T00:00:00.000Z)"
                "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
        ],
        indirect=["fastapi_app"],
        ids=[
            "t_before",
            "t_after",
            "t_meets",
            "t_metby",
            "t_overlaps",
            "t_overlappedby",
            # "t_starts",
            # "t_startedby",
            "t_during",
            "t_contains",
            # "t_finishes",
            # "t_finishedby",
            "t_equals",
            # "t_disjoint",
            "t_intersects",
        ],
    )
    @responses.activate
    def test_temporal_operators(self, client, endpoint, odata, expected_code):
        """Test used to group tests au temporal operators used to retrieve auxiliary data with DPR CQL2 filters."""
        responses.add(responses.GET, odata, json={"value": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == expected_code

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, page, is_last",
        [
            ("/auxip/collections/s2_adgs2_AUX_OBMEMC/items?token=next:page=", "3", True),
            ("/auxip/collections/s2_adgs2_AUX_OBMEMC/items?token=next:page=", "1", False),
            ("/cadip/collections/cadip_session_by_id_list_big/items?token=next:page=", "3", True),
            ("/cadip/collections/cadip_session_by_id_list_big/items?token=next:page=", "1", False),
        ],
    )
    @responses.activate
    def test_token_in_url(
        self,
        client,
        adgs_response_10_items,
        cadip_session_response_10_items,
        endpoint,
        page,
        is_last,
    ):
        """Used to test if application correctly builds next/previous token."""
        base_cadip_uri = (
            "http://127.0.0.1:5000/Sessions?$filter=SessionId in ("
            "'S1A_20200105072204051312','S1A_20200105072204051313','S1A_20200105072204051314',"
            "'S1A_20200105072204051315','S1A_20200105072204051316','S1A_20200105072204051317',"
            "'S1A_20200105072204051318','S1A_20200105072204051319','S1A_20200105072204051310',"
            "'S1A_20200105072204051311')&$orderby=PublicationDate desc&"
            f"$top=10&$skip={(int(page) - 1) * 10}"
        )
        base_cadip_files_uris = [
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051312'&$top=1000&$skip=0",
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051313'&$top=1000&$skip=0",
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051314'&$top=1000&$skip=0",
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051315'&$top=1000&$skip=0",
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051316'&$top=1000&$skip=0",
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051317'&$top=1000&$skip=0",
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051318'&$top=1000&$skip=0",
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051319'&$top=1000&$skip=0",
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051311'&$top=1000&$skip=0",
        ]
        base_adgs_uri = (
            "http://127.0.0.1:5001/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name%20eq%20'productType'%20and%20"
            "att/OData.CSC.StringAttribute/Value%20eq%20'AUX_OBMEMC')&"
            "$orderby=PublicationDate%20desc&"
            f"$top=10&$skip={(int(page) - 1) * 10}&"
            "$expand=Attributes"
        )
        responses.add(
            responses.GET,
            base_cadip_uri,
            json={"value": []} if is_last else cadip_session_response_10_items,
            status=200,
        )
        for base_cadip_files_uri in base_cadip_files_uris:
            responses.add(responses.GET, base_cadip_files_uri, json={"value": []}, status=200)
        responses.add(
            responses.GET,
            base_adgs_uri,
            json={"value": []} if is_last else adgs_response_10_items,
            status=200,
        )
        response = client.get(endpoint + page)
        assert response.status_code == status.HTTP_200_OK

        base_url = str(response.url).split("token", maxsplit=1)[0]
        next_token = quote(f"next:page={int(page) + 1}")
        prev_token = quote(f"prev:page={int(page) - 1}")
        next_url = f"{base_url}token={next_token}"
        prev_url = f"{base_url}token={prev_token}"
        # If this is last page (No results returned, check that "next" link doesn't exist.)
        if is_last:
            assert not any(link["rel"] == "next" for link in response.json()["links"])

            # Check that "previous" link exists
            assert any(link["rel"] == "previous" for link in response.json()["links"])
            # Check content and href of "previous" link
            assert {
                "rel": "previous",
                "type": "application/geo+json",
                "method": "GET",
                "href": prev_url,
                "title": "Previous link",
            } in response.json()["links"]
        else:
            # If this is first page (1) check that "previous" link doesn't exist.
            assert any(link["rel"] == "next" for link in response.json()["links"])
            # Check content and href of "next" link
            assert {
                "rel": "next",
                "type": "application/geo+json",
                "method": "GET",
                "href": next_url,
                "title": "Next link",
            } in response.json()["links"]

            # Check that "previous" link exists
            assert not any(link["rel"] == "previous" for link in response.json()["links"])


class TestCollection:
    """Class used to group tests for */collections/{collection_id}"""

    def setup(self, selector, cadip_response, adgs_response):
        """Helper function used to select fixture ouput for pickup response"""
        if selector == "adgs":
            return adgs_response
        return cadip_response

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, odata_request, href",
        [
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/collections/cadip_session_by_id",
                'http://127.0.0.1:5000/Sessions?$filter="SessionId eq S1A_20200105072204051312"&$top=20',
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/cadip/collections/cadip_session_by_id",
                    "title": "This collection",
                },
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/collections/s2_adgs2_AUX_OBMEMC",
                "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att"
                "/Name%20eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'AUX_OBMEMC')%22&"
                "$top=1000&$expand=Attributes",
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/auxip/collections/s2_adgs2_AUX_OBMEMC",
                    "title": "This collection",
                },
            ),
            (
                ROUTER_PREFIX_PRIP,
                "/prip/collections/S1A_L0_IW_RAW",
                "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att"
                "/Name%20eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'IW_RAW__0N')%22&"
                "$top=1000&$expand=Attributes",
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/prip/collections/S1A_L0_IW_RAW",
                    "title": "This collection",
                },
            ),
        ],
        indirect=["fastapi_app"],
    )
    def test_valid_collection_request(
        self,
        client,
        endpoint,
        odata_request,
        href,
        cadip_session_response,
        adgs_response,
    ):
        """Test a valid call to /collections endpoint, check that found collection is converted to a item link."""
        selected_response = self.setup(
            "adgs" if "auxip" in endpoint else "cadip",
            cadip_session_response,
            adgs_response,
        )
        responses.add(responses.GET, odata_request, json=selected_response, status=200)
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_200_OK
        assert href in response.json()["links"]

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize(
        "endpoint, odata_request, self_href",
        [
            (
                "/cadip/collections/cadip_session_by_id",
                'http://127.0.0.1:5000/Sessions?$filter="SessionId eq S1A_20200105072204051312"&$top=20',
                {
                    "href": "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
                    "rel": "license",
                    "title": "Legal notice on the use of Copernicus Sentinel Data and Service Information",
                },
            ),
            (
                "/auxip/collections/s2_adgs2_AUX_OBMEMC",
                "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att/Name%20"
                "eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'AUX_OBMEMC')%22&$top=1000"
                "&$expand=Attributes",
                {
                    "href": "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
                    "rel": "license",
                    "title": "Legal notice on the use of Copernicus Sentinel Data and Service Information",
                },
            ),
            (
                "/prip/collections/S1A_L0_IW_RAW",
                "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att/Name%20"
                "eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'IW_RAW__0N')%22&$top=1000"
                "&$expand=Attributes",
                {
                    "href": "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
                    "rel": "license",
                    "type": "application/pdf",
                    "title": "Legal notice on the use of Copernicus Sentinel Data and Service Information",
                },
            ),
        ],
    )
    def test_valid_empty_collection(self, client, endpoint, odata_request, self_href):
        """Test when response from pickup is empty, the result should still be 200 oK,
        and contain a link to the license."""
        responses.add(responses.GET, odata_request, json={"value": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_200_OK
        assert self_href in response.json()["links"]


@pytest.mark.parametrize("filter_type", ("cql", "query"))
@pytest.mark.parametrize("method", ("GET", "POST"))
@pytest.mark.parametrize(
    "fastapi_app, service",
    ((ROUTER_PREFIX_CADIP, "cadip"), (ROUTER_PREFIX_AUXIP, "adgs")),
    ids=["cadip", "adgs"],
    indirect=["fastapi_app"],
)
def test_search_parameters(
    mocker,
    client,
    filter_type,
    method,
    service,
    adgs_response,
    cadip_file_response,
    cadip_session_response,
):
    """Test all search parameters"""

    adgs = service == "adgs"
    cadip = service == "cadip"

    spy_search = mocker.spy(Provider, "search")

    if adgs:
        service_utils = adgs_utils
        expected_response = adgs_response
    elif cadip:
        service_utils = cadip_utils
        expected_response = cadip_session_response
    else:
        raise NotImplementedError

    # Read the first adgs or cadip collection, keep everything except the id and hardcoded query
    collection: dict = service_utils.read_conf()["collections"][0]
    collection = deepcopy(collection)  # copy the cached response before we modify it
    collection.pop("id")
    collection.pop("query")

    #
    # Mock a collection with no hardcoded query, another with single values, another with multiple values

    if adgs:
        query2 = {
            "productType": "AUX_OBMEMC",
            "platformShortName": "sentinel-1",
        }
        query3 = {
            "productType": "AUX_OBMEMC,type2",
            "platformShortName": "sentinel-1,sentinel-2",
        }
    elif cadip:
        query2 = {
            "Satellite": "S1A",
        }
        query3 = {
            "Satellite": "S1A,S2A",
        }
    else:
        raise NotImplementedError
    hardcoded_date = "2020-01-01T00:00:00.000Z/2022-01-01T00:00:00.000Z"
    hardcoded_limit = 10
    mocked_collections = [
        {"id": "col1", **collection},
        {
            "id": "col2",
            "query": {
                "PublicationDate": hardcoded_date,
                "top": hardcoded_limit,
                **query2,
            },
            **collection,
        },
        {
            "id": "col3",
            "query": {
                "PublicationDate": hardcoded_date,
                "top": hardcoded_limit,
                **query3,
            },
            **collection,
        },
    ]
    mocker.patch(
        "rs_server_common.stac_api_common.MockPgstac.all_collections",
        new_callable=mocker.PropertyMock,
        return_value=lambda: mocked_collections,
    )
    mocker.patch(f"{service_utils.__name__}.read_conf", return_value={"collections": mocked_collections})

    #
    # User given parameters

    # Static values
    user_ids = "id1,id2"
    user_datetime = "2020-01-01T00:00:00.000Z/2023-01-01T00:00:00.000Z"
    user_limit = 15  # User-defined 'limit' value has higher priority over the collection hardcoded 'top' value
    user_params = {
        "limit": user_limit,
        "datetime": user_datetime,
    }
    user_product_type = "type2"
    user_platform = "sentinel-2a"
    user_constellation = "sentinel-2"
    user_satellite = cadip_utils.cadip_map_mission(user_platform, user_constellation)
    user_sortby = ""
    if adgs:
        user_sortby = "created"
    if cadip:
        user_sortby = "published"

    # cql or query filter, for get or post requests
    if adgs:
        get_cql = f" AND product:type='{user_product_type}'"
        get_query = f""","product:type": {{"eq": "{user_product_type}"}}"""
        post_cql = [{"args": [{"property": "product:type"}, user_product_type], "op": "="}]
        post_query = {"product:type": {"eq": user_product_type}}
    else:
        get_cql = ""
        get_query = ""
        post_cql = []
        post_query = {}

    # GET parameters
    if method == "GET":
        user_params.update(
            {
                "ids": user_ids,
                "limit": user_limit,
                "sortby": f"+{user_sortby}",
            },
        )
        if filter_type == "cql":
            user_params.update(
                {"filter": f"platform='{user_platform}' AND constellation='{user_constellation}'{get_cql}"},
            )
        if filter_type == "query":
            user_params.update(
                {
                    "query": (
                        f"""{{"platform": {{"eq": "{user_platform}"}},"""
                        f"""\"constellation": {{"eq": "{user_constellation}"}}"""
                        f"{get_query}}}"
                    ),
                },
            )

    # POST parameters
    if method == "POST":
        user_params.update(
            {
                "ids": [id.strip() for id in user_ids.split(",")],
                "limit": user_limit,
                "sortby": [{"direction": "asc", "field": user_sortby}],
            },
        )
        if filter_type == "cql":
            user_params.update(
                {
                    "filter": {
                        "args": [
                            {"args": [{"property": "platform"}, "sentinel-2a"], "op": "="},
                            {"args": [{"property": "constellation"}, "sentinel-2"], "op": "="},
                            *post_cql,
                        ],
                        "op": "and",
                    },
                },
            )
        if filter_type == "query":
            user_params.update(
                {
                    "query": {
                        "platform": {"eq": "sentinel-2a"},
                        "constellation": {"eq": "sentinel-2"},
                        **post_query,
                    },
                },
            )

    # Call the /search endpoint for each collection
    for collection in mocked_collections:
        collection_id = collection["id"]

        # Copy and modify user params
        collection_params = deepcopy(user_params)
        if method == "GET":
            collection_params["collections"] = collection_id
        elif method == "POST":
            collection_params["collections"] = [collection_id]

            # Do a first call with the user query/filter, and a second call without
            for user_query in (True, False):

                # Remove the user query, but keep the datetime and others...
                if not user_query:
                    collection_params.pop("query", None)
                    collection_params.pop("filter", None)

            # NOTE: the OData queries are logged in eodag_provider.py when calling self.client.search
            # if the reponse is not mocked.
            # Decode the query (for better readability) using: https://meyerweb.com/eric/tools/dencoder/
            # TODO after fixing rs-server, these parameters should appear in the OData request:
            #  - sortBy (RSPY-131)
            if adgs:
                uids = f"('{user_ids.split(',', 1)[0]}','{user_ids.split(',', 1)[1]}')"
                odata_no_query = (
                    "http://127.0.0.1:5000/Products?$filter="
                    f"Name in {uids} and "
                    "(PublicationDate gt {date_min} or PublicationDate eq {date_min}) and "
                    "(PublicationDate lt {date_max} or PublicationDate eq {date_max})"
                    "&$orderby=PublicationDate%20asc&$top=15&$skip=0&$expand=Attributes"
                )
                odata_query = (
                    "http://127.0.0.1:5000/Products?$filter="
                    f"Name in {uids} and "
                    "(PublicationDate gt {date_min} or PublicationDate eq {date_min}) and "
                    "(PublicationDate lt {date_max} or PublicationDate eq {date_max}) "
                    "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
                    "and att/OData.CSC.StringAttribute/Value {product_type_op} {product_type}) "
                    "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' "
                    "and att/OData.CSC.StringAttribute/Value {constellation_op} {constellation})"
                    "&$orderby=PublicationDate%20asc&$top=15&$skip=0&$expand=Attributes"
                )
            elif cadip:
                # Add quote to the user_id
                user_ids_with_quote = ",".join([f"'{user_id}'" for user_id in user_ids.split(",")])
                odata_no_query = (
                    "http://127.0.0.1:5000/Sessions?$filter="
                    f"SessionId in ({user_ids_with_quote}) "
                    "and (PublicationDate gt {date_min} or PublicationDate eq {date_min}) "
                    "and (PublicationDate lt {date_max} or PublicationDate eq {date_max})"
                    "&$orderby=PublicationDate%20asc&$top=15&$skip=0"
                )
                odata_query = (
                    "http://127.0.0.1:5000/Sessions?$filter="
                    f"SessionId in ({user_ids_with_quote}) "
                    "and Satellite {satellite_op} {satellite} "
                    "and (PublicationDate gt {date_min} or PublicationDate eq {date_min}) "
                    "and (PublicationDate lt {date_max} or PublicationDate eq {date_max})"
                    "&$orderby=PublicationDate%20asc&$top=15&$skip=0"
                )
            else:
                raise NotImplementedError

            # The first collection has no hardcoded query. So either we use the user query.
            # Or, if missing, we query on everything.
            if collection_id == "col1":
                odata = odata_query if user_query else odata_no_query
                date_min = user_datetime.split("/", maxsplit=1)[0]
                # date_max = (
                #     user_datetime.split("/")[1].replace(".000Z", ".999Z")
                #     if method == "GET"
                #     else user_datetime.split("/")[1]
                # )
                date_max = user_datetime.split("/")[1]
                product_type = user_product_type
                constellation = user_constellation
                satellite = user_satellite
                limit = user_limit

            # The second collection has a query that does not intersect the user query.
            # So either it returns no results. Or, if the user query is missing, we use the collection query.
            elif collection_id == "col2":
                if cadip and user_query:
                    odata = odata_query
                elif user_query:
                    odata = None
                else:
                    odata = odata_query
                date_min = user_datetime.split("/", maxsplit=1)[0]  # intersection between user and hardcoded datetimes
                date_max = hardcoded_date.split("/")[1]
                product_type = collection["query"].get("productType")
                constellation = collection["query"].get("platformShortName")
                satellite = collection["query"].get("Satellite", "")
                if cadip and user_query:
                    satellite = f"{satellite},{user_satellite}" if satellite else user_satellite
                limit = user_limit

            # The third collection has a query with multiple values, that intersects only one user value.
            elif collection_id == "col3":
                odata = odata_query
                date_min = user_datetime.split("/", maxsplit=1)[0]  # intersection between user and hardcoded datetimes
                date_max = hardcoded_date.split("/")[1]
                limit = user_limit
                if user_query:
                    product_type = user_product_type
                    constellation = user_constellation
                    satellite = (
                        f"{collection['query'].get('Satellite', '')},{user_satellite}" if cadip else user_satellite
                    )
                else:
                    product_type = collection["query"].get("productType")
                    constellation = collection["query"].get("platformShortName")
                    satellite = collection["query"].get("Satellite", "")
            else:
                raise NotImplementedError

            collection_params["limit"] = limit

            # Mock the station response
            with responses.RequestsMock() as rsps:

                # If the query should return results
                if odata:

                    # Format the odata request with all possible parameters
                    if adgs:
                        constellation = constellation.upper()

                    def handle_multiple_values(value: str) -> str:
                        if value is None:
                            return None
                        if "," in value:
                            values = ",".join([f"'{val}'" for val in value.split(",")])
                            return f"({values})"
                        return f"'{value}'"

                    def in_or_eq(value: str) -> str:
                        return None if value is None else "in" if "," in value else "eq"

                    product_type = handle_multiple_values(product_type)
                    constellation = handle_multiple_values(constellation)
                    satellite = handle_multiple_values(satellite)

                    odata = odata.format(
                        date_min=date_min,
                        date_max=date_max,
                        product_type=product_type,
                        product_type_op=in_or_eq(product_type),
                        constellation=constellation,
                        constellation_op=in_or_eq(constellation),
                        satellite=satellite,
                        satellite_op=in_or_eq(satellite),
                    )

                    # Mock the reponse
                    rsps.add(
                        responses.GET,
                        odata,
                        status=status.HTTP_200_OK,
                        json=expected_response,
                    )
                    if cadip:
                        odata_query_files = (
                            "http://127.0.0.1:5000/Files?"
                            "$filter=SessionId%20eq%20'S1A_20200105072204051312'&$top=1000&$skip=0"
                        )
                        rsps.add(
                            responses.GET,
                            odata_query_files,
                            status=status.HTTP_200_OK,
                            json=cadip_file_response,
                        )
                    expect_result = True

                # The query should not return response
                else:
                    expect_result = False

                # Call the endpoint
                url = f"{os.getenv('router_prefix')}/search"
                if method == "GET":
                    response = client.get(url, params=collection_params)
                elif method == "POST":
                    response = client.post(url, json=collection_params)
                else:
                    raise NotImplementedError

                # Check that the search function was called and returned the expected result
                assert response.is_success, f"Response:{response}\nMock registered responses:{rsps.registered()}"
                features = response.json()["features"]
                if expect_result and adgs:
                    # 2 calls, one for sessions, one for files
                    assert spy_search.call_count == 1
                    assert len(spy_search.spy_return) == len(features) == 1  # expected_response
                elif expect_result and cadip:
                    # 2 calls, one for sessions, one for files
                    assert spy_search.call_count == 2
                    assert len(spy_search.spy_return) == 2 * len(features)  # expected_response
                else:
                    assert spy_search.call_count == 0
                    assert len(features) == 0
                spy_search.reset_mock()


@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_PRIP], ids=["prip"], indirect=["fastapi_app"])
@pytest.mark.parametrize(
    "collection_params, expected_odata",
    [
        (
            {"collections": "S1A_L0_IW_RAW", "datetime": "2022-06-26T06:30:34.558Z"},
            "http://127.0.0.1:5000/Products?"
            "$filter=PublicationDate eq 2022-06-26T06:30:34.558Z and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {"collections": "S1A_L0_IW_RAW", "datetime": "2022-06-26T06:30:34.558Z", "sortby": "+published"},
            "http://127.0.0.1:5000/Products?"
            "$filter=PublicationDate eq 2022-06-26T06:30:34.558Z and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate asc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {"collections": "S1A_L0_IW_RAW", "datetime": "2022-06-26T06:30:34.558Z/2023-06-26T06:30:34.558Z"},
            "http://127.0.0.1:5000/Products?"
            "$filter=(PublicationDate gt 2022-06-26T06:30:34.558Z or "
            "PublicationDate eq 2022-06-26T06:30:34.558Z) and "
            "(PublicationDate lt 2023-06-26T06:30:34.558Z or "
            "PublicationDate eq 2023-06-26T06:30:34.558Z) and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {"collections": "S1A_L0_IW_RAW", "filter": "platform='sentinel-1a' AND constellation='sentinel-1'"},
            "http://127.0.0.1:5000/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {"collections": "S1A_L0_IW_RAW", "datetime": "2022-06-26T06:30:34.558Z"},
            "http://127.0.0.1:5000/Products?"
            "$filter=PublicationDate eq 2022-06-26T06:30:34.558Z and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {"collections": "S1A_L0_IW_RAW", "datetime": "2022-06-26T06:30:34.558Z/2023-06-26T06:30:34.558Z"},
            "http://127.0.0.1:5000/Products?"
            "$filter=(PublicationDate gt 2022-06-26T06:30:34.558Z or PublicationDate eq 2022-06-26T06:30:34.558Z) and "
            "(PublicationDate lt 2023-06-26T06:30:34.558Z or PublicationDate eq 2023-06-26T06:30:34.558Z) and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {"collections": "S1A_L0_IW_RAW", "filter": "platform='sentinel-1a' AND constellation='sentinel-1'"},
            "http://127.0.0.1:5000/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": "S1A_L0_IW_RAW",
                "filter": "platform='sentinel-1a' AND constellation='sentinel-1'",
                "sortby": "+published",
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate asc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": "S1A_L0_IW_RAW",
                "filter": "platform='sentinel-1a' AND constellation='sentinel-1'",
                "limit": 5,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=5&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": "S1A_L0_IW_RAW",
                "filter": "platform='sentinel-1a' AND constellation='sentinel-1'",
                "page": 1,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {"collections": "S1A_L0_IW_RAW", "filter": "Name=ABCD AND constellation='sentinel-1'"},
            "http://127.0.0.1:5000/Products?"
            "$filter=contains(Name, 'ABCD') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": "S1A_L0_IW_RAW",
                "filter": "intersects='POLYGON((-10 0,-62 -10,-58 -10,-56 0,-60 0))' AND constellation='sentinel-1'",
                "filter-lang": "cql2-text",
                "limit": 10,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=OData.CSC.Intersects(area=geography'SRID=4326;POLYGON((-10 0,-62 -10,-58 -10,-56 0,-60 0))') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
    ],
    ids=[
        "collections_datetime",
        "collections_datetime_published",
        "collections_datetime2",
        "collections_filter",
        "datetime_instant",
        "datetime_range",
        "filter_platform_constellation",
        "filter_platform_constellation_sort_asc",
        "filter_platform_constellation_limit5",
        "filter_platform_constellation_page2",
        "filter_name_constellation",
        "collections_intersects",
    ],
)
def test_get_search_parameters_prip(client, mocker, prip_response, collection_params, expected_odata):
    """Test prip searching."""
    router_prefix = os.getenv("router_prefix")
    assert router_prefix is not None, "router_prefix must be set"
    url = f"{router_prefix.rstrip('/')}/search"

    mocker.patch(
        "rs_server_common.data_retrieval.eodag_provider.get_station_token",
        return_value={"access_token": "TEST_TOKEN"},
    )

    spy_search = mocker.spy(Provider, "search")

    responses.add(responses.GET, expected_odata, status=200, json=prip_response)

    r = client.get(url, params=collection_params)
    assert r.status_code == status.HTTP_200_OK, r.text
    urls: list[str] = [str(getattr(c.request, "url", "") or "") for c in responses.calls]
    products = [u for u in urls if u.startswith("http://127.0.0.1:5000/Products?")]
    prod_url: str = products[-1]

    assert unquote(prod_url) == expected_odata, f"\nExpected:\n{expected_odata}\nGot:\n{unquote(prod_url)}"
    assert spy_search.call_count == 1
    spy_search.reset_mock()


@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_PRIP], ids=["prip"], indirect=["fastapi_app"])
@pytest.mark.parametrize(
    "collection_params, expected_odata",
    [
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "filter-lang": "cql2-json",
                "filter": {"op": "and", "args": [{"op": "=", "args": [{"property": "Name"}, "ABCD"]}]},
                "limit": 10,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=contains(Name, 'ABCD') and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "limit": 10,
                "filter-lang": "cql2-json",
                "filter": {"op": "=", "args": [{"property": "datetime"}, "2022-06-26T06:30:34.558Z"]},
                "sortby": [{"field": "published", "direction": "desc"}],
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=ContentDate/Start eq 2022-06-26T06:30:34.558Z "
            "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "limit": 10,
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "start_datetime"}, "2020-06-26T06:30:34.558Z"]},
                        {"op": "=", "args": [{"property": "end_datetime"}, "2023-06-26T06:30:34.558Z"]},
                    ],
                },
                "sortby": [{"field": "published", "direction": "desc"}],
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=ContentDate/Start eq 2020-06-26T06:30:34.558Z and ContentDate/End eq 2023-06-26T06:30:34.558Z "
            "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'beginningDateTime' and "
            "att/OData.CSC.StringAttribute/Value eq '2020-06-26T06:30:34.558Z') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'endingDateTime' "
            "and att/OData.CSC.StringAttribute/Value eq '2023-06-26T06:30:34.558Z')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "Name"}, "ABCD"]},
                        {"op": "=", "args": [{"property": "platform"}, "sentinel-1a"]},
                    ],
                },
                "limit": 10,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=contains(Name, 'ABCD') and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') "
            "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' "
            "and att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1') "
            "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformSerialIdentifier' "
            "and att/OData.CSC.StringAttribute/Value eq 'A')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "Name"}, "ABCD"]},
                        {"op": "=", "args": [{"property": "constellation"}, "sentinel-1"]},
                    ],
                },
                "limit": 10,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=contains(Name, 'ABCD') and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
            "and att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') "
            "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' "
            "and att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "constellation"}, "sentinel-1"]},
                        {
                            "op": "intersects",
                            "args": [{"property": "geometry"}, "POLYGON((-60 0,-62 -10,-58 -10,-56 0,-60 0))"],
                        },
                    ],
                },
                "limit": 10,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=OData.CSC.Intersects(area=geography'SRID=4326;POLYGON((-60 0,-62 -10,-58 -10,-56 0,-60 0))') "
            "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name "
            "eq 'platformShortName' and att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "constellation"}, "sentinel-1"]},
                        {
                            "op": "intersects",
                            "args": [
                                {"property": "geometry"},
                                {
                                    "type": "polygon",
                                    "coordinates": [[[-60, 0], [-62, -10], [-58, -10], [-56, 0], [-60, 0]]],
                                },
                            ],
                        },
                    ],
                },
                "limit": 10,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=OData.CSC.Intersects(area=geography'SRID=4326;POLYGON((-60 0, -62 -10, -58 -10, -56 0, -60 0))') "
            "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name "
            "eq 'platformShortName' and att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "limit": 10,
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {
                            "op": "=",
                            "args": [
                                {"property": "id"},
                                "S1A_IW_RAW__0NSH_20220626T050533_20220626T051038_043829_053B7F_203C",
                            ],
                        },
                        {"op": "=", "args": [{"property": "processing:facility"}, "S1 Production Service-SERCO"]},
                    ],
                },
                "sortby": [{"field": "published", "direction": "desc"}],
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=contains(Name, 'S1A_IW_RAW__0NSH_20220626T050533_20220626T051038_043829_053B7F_203C') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') "
            "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'processingCenter' and "
            "att/OData.CSC.StringAttribute/Value eq 'S1 Production Service-SERCO')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "platform"}, "sentinel-1a"]},
                        {"op": "=", "args": [{"property": "created"}, "2022-06-26T06:30:34.558Z"]},
                    ],
                },
                "limit": 10,
                "sortby": [{"field": "file:size", "direction": "desc"}],
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformSerialIdentifier' and "
            "att/OData.CSC.StringAttribute/Value eq 'A') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'processingDate' and "
            "att/OData.CSC.StringAttribute/Value eq '2022-06-26T06:30:34.558Z')"
            "&$orderby=ContentLength desc&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "platform"}, "sentinel-1a"]},
                        {"op": "=", "args": [{"property": "sat:absolute_orbit"}, 10000]},
                        {"op": "=", "args": [{"property": "sat:orbit_state"}, "descending"]},
                        {"op": "=", "args": [{"property": "processing:version"}, "2.0"]},
                    ],
                },
                "limit": 10,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' and "
            "att/OData.CSC.StringAttribute/Value eq 'SENTINEL-1') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformSerialIdentifier' and "
            "att/OData.CSC.StringAttribute/Value eq 'A') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'processorVersion' and "
            "att/OData.CSC.StringAttribute/Value eq '2.0') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'orbitNumber' and "
            "att/OData.CSC.StringAttribute/Value eq '10000') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'orbitDirection' and "
            "att/OData.CSC.StringAttribute/Value eq 'DESCENDING')&$orderby=PublicationDate desc"
            "&$top=10&$skip=0&$expand=Attributes",
        ),
        (
            {
                "collections": ["S1A_L0_IW_RAW"],
                "filter-lang": "cql2-json",
                "filter": {
                    "op": "and",
                    "args": [
                        {"op": "=", "args": [{"property": "sat:absolute_orbit"}, "43829"]},
                        {"op": "=", "args": [{"property": "processing:version"}, "2.0"]},
                        {"op": "=", "args": [{"property": "sat:orbit_state"}, "ascending"]},
                        {"op": "=", "args": [{"property": "sat:relative_orbit"}, "43829"]},
                    ],
                },
                "limit": 10,
            },
            "http://127.0.0.1:5000/Products?"
            "$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
            "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'processorVersion' and "
            "att/OData.CSC.StringAttribute/Value eq '2.0') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'orbitNumber' and "
            "att/OData.CSC.StringAttribute/Value eq '43829') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'relativeOrbitNumber' and "
            "att/OData.CSC.StringAttribute/Value eq '43829') and "
            "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'orbitDirection' and "
            "att/OData.CSC.StringAttribute/Value eq 'ASCENDING')&$orderby=PublicationDate desc"
            "&$top=10&$skip=0&$expand=Attributes",
        ),
    ],
    ids=[
        "collections_Name",
        "collections_datetime_published",
        "collections_start_end_datetime",
        "collections_Name_platform",
        "collections_Name_constellation",
        "collections_constellation_geometry",
        "collections_constellation_geometry2",
        "collections_id",
        "collections_platform_created",
        "collections_platform_orbit",
        "collections_platform_orbit2",
    ],
)
def test_post_search_parameters_prip(client, mocker, prip_response, collection_params, expected_odata):
    """Test prip searching."""
    router_prefix = os.getenv("router_prefix")
    assert router_prefix is not None, "router_prefix must be set"
    url = f"{router_prefix.rstrip('/')}/search"

    mocker.patch(
        "rs_server_common.data_retrieval.eodag_provider.get_station_token",
        return_value={"access_token": "TEST_TOKEN"},
    )

    spy_search = mocker.spy(Provider, "search")

    responses.add(responses.GET, expected_odata, status=200, json=prip_response)

    r = client.post(url, json=collection_params)

    assert r.status_code == status.HTTP_200_OK, r.text
    urls: list[str] = [str(getattr(c.request, "url", "") or "") for c in responses.calls]
    products = [u for u in urls if u.startswith("http://127.0.0.1:5000/Products?")]
    prod_url: str = products[-1]

    assert unquote(prod_url) == expected_odata, f"\nExpected:\n{expected_odata}\nGot:\n{unquote(prod_url)}"
    assert spy_search.call_count == 1
    spy_search.reset_mock()


@pytest.mark.parametrize(
    "fastapi_app",
    [ROUTER_PREFIX_AUXIP],
    ids=["adgs"],
    indirect=["fastapi_app"],
)
def test_search_all_collections(
    mocker,
    client,
    adgs_response,
):
    """Test searching all collections at the same time."""
    spy_search = mocker.spy(Provider, "search")

    # Read the first adgs or cadip collection, keep everything except the id and hardcoded query
    collection = adgs_utils.read_conf()["collections"][0]
    collection = deepcopy(collection)  # copy the cached response before we modify it
    collection.pop("id")
    collection.pop("query")

    # Mock n collections
    collection_count = 10
    mocked_collections = [{"id": f"col{i}", **collection} for i in range(collection_count)]
    mocker.patch(
        "rs_server_common.stac_api_common.MockPgstac.all_collections",
        new_callable=mocker.PropertyMock,
        return_value=lambda: mocked_collections,
    )
    mocker.patch(f"{adgs_utils.__name__}.read_conf", return_value={"collections": mocked_collections})

    # Mock response
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "http://127.0.0.1:5000/Products?$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
            status=status.HTTP_200_OK,
            json=adgs_response,
        )

        # Search all collections at the same time
        url = f"{os.getenv('router_prefix')}/search"
        response = client.get(url)

        # We have mocked the same response for all n collections,
        # so we should have a single result and a single call since RSPY-706
        assert response.is_success
        features = response.json()["features"]
        assert spy_search.call_count == 1
        assert len(spy_search.spy_return) == len(features) == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint",
    [
        (
            # PRIP endpoint example (bbox → intersects)
            "/prip/collections/S1A_L0_IW_RAW/items?bbox=100.0,0.0,105.0,1.0"
        ),
    ],
)
@responses.activate
def test_prip_bbox_converted_to_intersects(
    client: TestClient,
    endpoint: str,
):
    """
    Test that for PRIP collections, a bbox parameter is correctly converted
    into an 'intersects' polygon (WKT) in the outgoing OData request.
    """

    # Mock the expected backend call
    responses.add(
        responses.GET,
        (
            "http://127.0.0.1:5000/Products?"
            "$filter=OData.CSC.Intersects(area=geography'SRID=4326;POLYGON ((105 0, 105 1, 100 1, 100 0, 105 0))')"
            " and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/"
            "OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes"
        ),
        json={"value": []},
        status=200,
    )
    response = client.get(endpoint)

    assert response.status_code == status.HTTP_200_OK

    called_url = unquote(responses.calls[1].request.url or "")

    match = re.search(r"POLYGON\s*\(\((.*?)\)\)", called_url)
    assert match, f"No POLYGON found in backend URL: {called_url}"

    actual_polygon = match.group(0)
    # the bbox should be translated to (105 0, 105 1, 100 1, 100 0, 105 0) as per box(west, south, east, north)
    expected_polygon = "POLYGON ((105 0, 105 1, 100 1, 100 0, 105 0))"

    assert actual_polygon == expected_polygon


@pytest.mark.unit
@pytest.mark.parametrize(
    "bbox, filter_wkt, expected_intersection_wkt, should_intersect",
    [
        # bbox as list, overlapping
        (
            [100.0, 0.0, 105.0, 1.0],
            "POLYGON((104.0 0.5,106.0 0.5,106.0 1.5,104.0 1.5,104.0 0.5))",
            "POLYGON((104.0 0.5,105.0 0.5,105.0 1.0,104.0 1.0,104.0 0.5))",
            True,
        ),
        # bbox as list, not overlapping
        ([100.0, 0.0, 101.0, 1.0], "POLYGON((104.0 0.5,106.0 0.5,106.0 1.5,104.0 1.5,104.0 0.5))", None, False),
        # bbox as string, overlapping
        (
            "100.0,0.0,105.0,1.0",
            "POLYGON((104.0 0.5,106.0 0.5,106.0 1.5,104.0 1.5,104.0 0.5))",
            "POLYGON((104.0 0.5,105.0 0.5,105.0 1.0,104.0 1.0,104.0 0.5))",
            True,
        ),
    ],
)
@responses.activate
def test_prip_bbox_intersection(client: TestClient, bbox, filter_wkt, expected_intersection_wkt, should_intersect):
    """
    Test bbox and filter 'intersects' logic with bbox as list or string.
    """

    # Convert bbox to coords
    if isinstance(bbox, str):
        coords = [float(x) for x in bbox.split(",")]
    elif isinstance(bbox, list):
        coords = list(map(float, bbox))
    else:
        raise ValueError("bbox must be list or str")

    bbox_poly = box(*coords)
    filter_poly = wkt_loads(filter_wkt)

    if bbox_poly.intersects(filter_poly):
        intersection_poly = bbox_poly.intersection(filter_poly)
        assert intersection_poly.equals(
            wkt_loads(expected_intersection_wkt),
        ), f"Intersection mismatch:\nExpected: {expected_intersection_wkt}\nGot: {intersection_poly.wkt}"
        assert should_intersect == bbox_poly.intersects(filter_poly)

        # Mock GET request for overlapping bbox
        responses.add(
            responses.GET,
            (
                "http://127.0.0.1:5000/Products?"
                "$filter=OData.CSC.Intersects(area=geography'SRID=4326;POLYGON "
                "((105 1, 105 0.5, 104 0.5, 104 1, 105 1))')"
                " and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
                "att/OData.CSC.StringAttribute/Value eq 'IW_RAW__0N')"
                "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes"
            ),
            json={"value": []},
            status=200,
        )

        # Build URL query
        bbox_str = ",".join(map(str, coords))
        endpoint = f"/prip/collections/S1A_L0_IW_RAW/items?bbox={bbox_str}&filter=intersects={filter_wkt}"
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_200_OK

    else:
        # Mock GET request for non-overlapping bbox
        bbox_str = ",".join(map(str, coords))
        endpoint = f"/prip/collections/S1A_L0_IW_RAW/items?bbox={bbox_str}&filter=intersects={filter_wkt}"
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
