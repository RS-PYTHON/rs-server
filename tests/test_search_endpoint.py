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

"""Unittests for rs-server search endpoints."""
import os
from copy import deepcopy

import pytest
import requests
import responses
import yaml
from fastapi import HTTPException, status
from pydantic import ValidationError
from rs_server_adgs import adgs_utils
from rs_server_adgs.adgs_utils import auxip_map_mission
from rs_server_cadip import cadip_utils
from rs_server_cadip.cadip_utils import cadip_map_mission
from rs_server_common.data_retrieval.provider import CreateProviderFailed, Provider

from tests.app import ROUTER_PREFIX_AUXIP, ROUTER_PREFIX_CADIP

# pylint: disable=too-few-public-methods, too-many-arguments, too-many-locals,
# pylint: disable=too-many-branches, too-many-lines, too-many-statements


@pytest.mark.unit
@responses.activate
def test_valid_search_by_session_id(expected_products, client, mock_token_validation):
    """Test used for searching a file by a given session id or ids."""
    # Test with no parameters
    assert client.get("/cadip/cadip/cadu/search").status_code == status.HTTP_400_BAD_REQUEST
    mock_token_validation("cadip")
    responses.add(
        responses.GET,
        "http://127.0.0.1:5000/Files?$filter=SessionId eq 'session_id1'"
        "&$orderby=PublicationDate desc&$top=1000&$skip=0",
        json={"value": expected_products[0]},
        status=200,
    )
    # Test a request with only all files from session_id1
    response = client.get("/cadip/cadip/cadu/search?session_id=session_id1")
    assert response.status_code == status.HTTP_200_OK
    # test that session_id1 is correctly mapped
    assert response.json()["features"][0]["properties"]["cadip:session_id"] == "session_id1"

    # Test a request with all files from multiple sessions
    responses.add(
        responses.GET,
        "http://127.0.0.1:5000/Files?$filter=SessionId in ('session_id2', 'session_id3')"
        "&$orderby=PublicationDate desc&$top=1000&$skip=0",
        json={"value": expected_products[1:]},
        status=200,
    )
    response = client.get("/cadip/cadip/cadu/search?session_id=session_id2,session_id3")
    assert response.status_code == status.HTTP_200_OK

    # test that returned products are from session_id2 and session_id3
    assert response.json()["features"][0]["properties"]["cadip:session_id"] == "session_id2"
    assert response.json()["features"][1]["properties"]["cadip:session_id"] == "session_id3"

    # Nominal case, combined session_id and datetime
    responses.add(
        responses.GET,
        "http://127.0.0.1:5000/Files?$filter=SessionId eq 'session_id2' and PublicationDate gte 2022-01-01T12:00:"
        "00.000Z and PublicationDate lte 2023-12-30T12:00:00.000Z&$orderby=PublicationDate desc&$top=1000&$skip=0",
        json={"value": expected_products},
        status=200,
    )
    endpoint = "/cadip/CADIP/cadu/search?datetime=2022-01-01T12:00:00Z/2023-12-30T12:00:00Z&session_id=session_id2"
    assert client.get(endpoint).status_code == status.HTTP_200_OK


# Deprecated tests, to be removed.
@pytest.mark.unit
@responses.activate
def test_adgs_search_aux(client, mock_token_validation, mocker):
    """Tests for /adgs/aux/search"""
    response = client.get("/adgs/aux/search")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    mock_token_validation("adgs")
    responses.add(
        responses.GET,
        "http://127.0.0.1:5000/Products?$filter=PublicationDate gte 2022-01-01T12:00:00.000Z"
        " and PublicationDate lte 2023-12-30T12:00:00.000Z&$orderby=PublicationDate desc"
        "&$top=1000&$skip=0&$expand=Attributes",
        json={"value": []},
        status=200,
    )
    endpoint = "/adgs/aux/search?datetime=2022-01-01T12:00:00Z/2023-12-30T12:00:00Z"
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_200_OK
    mocker.patch("rs_server_adgs.api.adgs_search.init_adgs_provider", side_effect=CreateProviderFailed)
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    mocker.patch("rs_server_adgs.api.adgs_search.init_adgs_provider", side_effect=requests.exceptions.ConnectionError)
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    mocker.patch("rs_server_adgs.api.adgs_search.init_adgs_provider", side_effect=Exception)
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


#########################
# Reworked tests section
#########################


class TestOperatorDefinedCollections:
    """Class used to group tests for operator-defined collections."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, code",
        [
            ("/cadip/collections/cadip_session_incomplete/items", status.HTTP_422_UNPROCESSABLE_ENTITY),
            ("/cadip/collections/cadip_session_incomplete_no_stop/items", status.HTTP_400_BAD_REQUEST),
            ("/cadip/collections/cadip_session_incomplete_no_start/items", status.HTTP_400_BAD_REQUEST),
            ("/auxip/collections/adgs_invalid_no_start/items", status.HTTP_400_BAD_REQUEST),
            ("/auxip/collections/adgs_invalid_no_stop/items", status.HTTP_400_BAD_REQUEST),
        ],
    )
    def test_invalid_defined_collections(self, client, mocker, mock_token_validation, endpoint, code):
        """Test cases with invalid defined collections requests send to /session endpoint"""
        # Mock the env var RSPY_USE_MODULE_FOR_STATION_TOKEN to True. This will trigger the
        # usage of the internal token module  for getting the token and setting it to the eodag
        mock_token_validation()
        mocker.patch("rs_server_common.authentication.authentication_to_external.env_bool", return_value=True)
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
        assert auxip_map_mission(platform, constellation) == (short_name, serial_id)

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
            auxip_map_mission(platform, constellation)

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
            (None, "sentinel-1", "S1A, S1B, S1C"),
            (None, "sentinel-2", "S2A, S2B, S2C"),
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
        [(ROUTER_PREFIX_CADIP, "/cadip", "/cadip/collections"), (ROUTER_PREFIX_AUXIP, "/auxip", "/auxip/collections")],
        indirect=["fastapi_app"],
    )
    def test_local_landing_pages(self, client, endpoint, collection_link):
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
            ("/auxip/collections", ["rs_adgs_landing_page", "rs_adgs_authTest_read"]),
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
            ("/auxip/collections", ["rs_adgs_landing_page"], "rs_server_adgs.api.adgs_search.Request.state"),
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
        [("/cadip/collections", "RSPY_CADIP_SEARCH_CONFIG"), ("/auxip/collections", "RSPY_ADGS_SEARCH_CONFIG")],
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
            (ROUTER_PREFIX_CADIP, "/cadip/collections/cadip_session_by_id_list/items/sessionId"),
        ],
        indirect=["fastapi_app"],
    )
    def test_cadip_validation_errors(self, client, mocker, endpoint):
        """Test used to mock a validation error on pydantic model, should return HTTP 422."""
        mocker.patch(
            "rs_server_cadip.api.cadip_search.process_session_search",
            side_effect=ValidationError.from_exception_data("Invalid data", line_errors=[]),
        )
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

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
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.unit
    def test_adgs_search_error(self, client, mocker):
        """Test ADGS process_product_search throwing errors"""
        mocker.patch("rs_server_adgs.api.adgs_search.init_adgs_provider", side_effect=CreateProviderFailed)
        response = client.get("/auxip/collections/adgs_by_platform/items")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {"detail": "Bad station identifier: "}
        mocker.patch(
            "rs_server_adgs.api.adgs_search.init_adgs_provider",
            side_effect=requests.exceptions.ConnectionError,
        )
        response = client.get("/auxip/collections/adgs_by_platform/items")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"detail": "Station ADGS connection error: "}
        mocker.patch("rs_server_adgs.api.adgs_search.init_adgs_provider", side_effect=Exception)
        response = client.get("/auxip/collections/adgs_by_platform/items")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"detail": "General failure: "}


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
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint",
        [(ROUTER_PREFIX_AUXIP, "/auxip/search?collection=adgs_by_platform")],
        indirect=["fastapi_app"],
    )
    def test_adgs_collection_creation_failure(self, client, mocker, endpoint):
        """Test used to generate a KeyError while Collection is created, should return HTTP 422."""
        mocker.patch("rs_server_adgs.api.adgs_search.process_product_search", side_effect=KeyError)
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


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
        client,
        mock_token_validation,
        cadip_feature,
        cadip_session_response,
        cadip_file_response,
    ):
        """Test a cadip pickup response with 2 assets is correctly mapped to a stac Feature
        Visit conftest to view content of cadip_feature and cadip_response.
        """
        # Mock pickup response and token validation
        mock_token_validation()
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
        response = client.get("/cadip/collections/cadip_session_by_id/items/S1A_20200105072204051312").json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response == cadip_feature, "Features don't match"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_CADIP], indirect=["fastapi_app"])
    def test_cadip_empty_feature_mapping(self, client, mock_token_validation, cadip_feature):
        """Test to verify the output of rs-server when pick-up point response is empty."""
        mock_token_validation()
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
        assert response.json()["detail"] == "Cadip session 'S1A_20200105072204051312' not found."
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_AUXIP], indirect=["fastapi_app"])
    def test_adgs_feature_mapping(self, client, mock_token_validation, adgs_feature, adgs_response):
        """Test mapping of an adgs reponse with expanded attributes"""
        mock_token_validation()
        responses.add(
            responses.GET,
            "http://127.0.0.1:5001/Products?$filter=contains(Name, "
            "'S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF') and Attributes/OData.CSC.StringAttribute"
            "/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq 'AUX_OBMEMC')"
            "&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
            json=adgs_response,
            status=200,
        )
        response = client.get(
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items/S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
        ).json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response == adgs_feature, "Features don't match"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_AUXIP], indirect=["fastapi_app"])
    def test_adgs_empty_feature_mapping(self, client, mock_token_validation, adgs_feature):
        """Test to verify the output of rs-server when pick-up point response is empty."""
        mock_token_validation()
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
        assert (
            response.json()["detail"]
            == "AUXIP item 'S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF' not found."
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, detail",
        [
            (
                "/auxip/collections/INVALID_COLLECTION/items/S1A_OPER_MPL_ORBPRE_20210214T021411_.EOF",
                {"detail": "Unknown AUXIP collection: 'INVALID_COLLECTION'"},
            ),
            (
                "/cadip/collections/INVALID_COLLECTION/items/S1A_20200105072204051312",
                {"detail": "Unknown CADIP collection: 'INVALID_COLLECTION'"},
            ),
        ],
    )
    def test_invalid_collection_mapping(self, client, endpoint, detail):
        """Test to verify the output of rs-server when given item collection is invalid."""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == detail

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize(
        "endpoint, odata_url, detail",
        [
            (
                "/auxip/collections/s2_adgs2_AUX_OBMEMC/items/INVALID_ITEM",
                "http://127.0.0.1:5001/Products?$filter=contains(Name, 'INVALID_ITEM') and Attributes/OData.CSC."
                "StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq "
                "'AUX_OBMEMC')&$orderby=PublicationDate desc&$top=1&$skip=0&$expand=Attributes",
                {"detail": "AUXIP item 'INVALID_ITEM' not found."},
            ),
        ],
    )
    def test_adgs_invalid_item_mapping(self, client, mock_token_validation, endpoint, odata_url, detail):
        """Test to verify the output of rs-server when given collection is valid and item is invalid."""
        mock_token_validation()
        responses.add(
            responses.GET,
            odata_url,
            json={"value": []},
            status=200,
        )
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == detail

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize(
        "endpoint, odata_session_url, odata_file_url, detail",
        [
            (
                "/cadip/collections/cadip_session_by_id/items/INVALID_ITEM",
                "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312'"
                "&$orderby=PublicationDate desc&$top=1&$skip=0",
                'http://127.0.0.1:5000/Files?$filter="SessionID eq S1A_20200105072204051312"&$top=20',
                {"detail": "Cadip session 'INVALID_ITEM' not found."},
            ),
        ],
    )
    def test_cadip_invalid_item_mapping(
        self,
        client,
        mock_token_validation,
        endpoint,
        odata_session_url,
        odata_file_url,
        detail,
    ):
        """Test to verify the output of rs-server when given collection is valid and item is invalid."""
        mock_token_validation()
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
        assert response.json() == detail


class TestFeatureCollectionOdataStacMapping:
    """Class that group unittests for /*/collections/{collection-id}/items mapping from odata to stac."""

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_CADIP], indirect=["fastapi_app"])
    def test_cadip_feature_collection_mapping(
        self,
        client,
        mock_token_validation,
        cadip_feature,
        cadip_file_response,
        cadip_session_response,
    ):
        """Test a cadip pickup response with 2 assets is correctly mapped to a stac Feature
        Visit conftest to view content of cadip_feature and cadip_response.
        """
        # Mock pickup response and token validation
        mock_token_validation()
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
        response = client.get("/cadip/collections/cadip_session_by_id/items").json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response["type"] == "FeatureCollection", "Type doesn't match"
        assert response["features"] == [cadip_feature], "Features don't match"

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize("fastapi_app", [ROUTER_PREFIX_AUXIP], indirect=["fastapi_app"])
    def test_adgs_feature_collection_mapping(self, client, mock_token_validation, adgs_feature, adgs_response):
        """Test mapping of an adgs reponse with expanded attributes"""
        mock_token_validation()
        responses.add(
            responses.GET,
            "http://127.0.0.1:5001/Products?$filter=Attributes/OData.CSC.StringAttribute/any(att:att/Name eq "
            "'productType' and att/OData.CSC.StringAttribute/Value eq 'AUX_OBMEMC')"
            "&$orderby=PublicationDate desc&$top=10&$skip=0&$expand=Attributes",
            json=adgs_response,
            status=200,
        )
        response = client.get("/auxip/collections/s2_adgs2_AUX_OBMEMC/items").json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response["type"] == "FeatureCollection", "Type doesn't match"
        assert response["features"] == [adgs_feature], "Features don't match"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, detail",
        [
            (
                "/auxip/collections/INVALID_COLLECTION/items",
                {"detail": "Unknown AUXIP collection: 'INVALID_COLLECTION'"},
            ),
            (
                "/cadip/collections/INVALID_COLLECTION/items",
                {"detail": "Unknown CADIP collection: 'INVALID_COLLECTION'"},
            ),
        ],
    )
    def test_feature_collection_not_found(self, client, endpoint, detail):
        """Test with an invalid collection request, should raise 404."""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == detail

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit='invalid_value'",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit='-5'",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=0",
            "/cadip/collections/cadip_session_by_id/items?limit='invalid_value'",
            "/cadip/collections/cadip_session_by_id/items?limit='-5'",
            "/cadip/collections/cadip_session_by_id/items?limit=0",
        ],
    )
    def test_invalid_limit_values(self, client, endpoint):
        """Test endpoint call with invalid limits (str, negative, 0)"""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert response.json()["detail"][0]["msg"] in (
            "Input should be a valid integer, unable to parse string as an integer",
            "Input should be greater than 0",
        )

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=1&page='invalid'",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=1&page=-5",
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=1&page='0'",
            "/cadip/collections/cadip_session_by_id/items?limit=1&page='invalid'",
            "/cadip/collections/cadip_session_by_id/items?limit=1&page=-5",
            "/cadip/collections/cadip_session_by_id/items?limit=1&page='0'",
        ],
    )
    def test_invalid_page_values(self, client, endpoint):
        """Test endpoint call with invalid pages (str, negative, 0)"""
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "Invalid page value" in response.json()["detail"]

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items?limit=1&page=1&sortby='invalid'",
            "/cadip/collections/cadip_session_by_id/items?limit=1&page=1&sortby='invalid'",
        ],
    )
    @responses.activate
    def test_invalid_sortby_values(self, client, mock_token_validation, endpoint):
        """Test endpoint call with invalid pages (str, negative, 0)"""
        mock_token_validation()
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "parameter is not sortable" in response.json()["detail"]

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "fastapi_app, endpoint, odata, expected_code",
        [
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=2018-02-12T23:20:50.888Z",
                "http://127.0.0.1:5000/Products?$filter=PublicationDate eq 2018-02-12T23:20:50.888Z"
                "&$orderby=PublicationDate desc&$top=10000&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=2018-02-12T23:20:50.000Z/2019-02-12T23:20:50.001Z",
                "http://127.0.0.1:5000/Products?$filter=PublicationDate gte 2018-02-12T23:20:50.000Z and "
                "PublicationDate lte 2019-02-12T23:20:50.001Z&$orderby=PublicationDate desc&$top=10000&"
                "$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=2018-02-12T23:20:50Z/..",
                "http://127.0.0.1:5000/Products?$filter=PublicationDate gte 2018-02-12T23:20:50.000Z"
                "&$orderby=PublicationDate desc&$top=10000&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_AUXIP,
                "/auxip/search?collections=adgs&datetime=../2018-02-12T23:20:50.001Z",
                "http://127.0.0.1:5000/Products?$filter=PublicationDate lte 2018-02-12T23:20:50.001Z"
                "&$orderby=PublicationDate desc&$top=10000&$skip=0&$expand=Attributes",
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
                "PublicationDate desc&$top=10000&$skip=0&$expand=Attributes",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=2018-02-12T23:20:50.777Z",
                "http://127.0.0.1:5000/Sessions?$filter=PublicationDate eq 2018-02-12T23:20:50.777Z"
                "&$orderby=PublicationDate desc&$top=10000&$skip=0",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=2018-02-12T23:20:50Z/2019-02-12T23:20:50Z",
                "http://127.0.0.1:5000/Sessions?$filter=PublicationDate gte 2018-02-12T23:20:50.000Z and "
                "PublicationDate lte 2019-02-12T23:20:50.000Z&$orderby=PublicationDate desc&$top=10000&$skip=0",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=2018-02-12T23:20:50Z/..",
                "http://127.0.0.1:5000/Sessions?$filter=PublicationDate gte 2018-02-12T23:20:50.000Z"
                "&$orderby=PublicationDate desc&$top=10000&$skip=0",
                status.HTTP_200_OK,
            ),
            (
                ROUTER_PREFIX_CADIP,
                "/cadip/search?collections=cadip&datetime=../2018-02-12T23:20:50Z",
                "http://127.0.0.1:5000/Sessions?$filter=PublicationDate lte 2018-02-12T23:20:50.000Z"
                "&$orderby=PublicationDate desc&$top=10000&$skip=0",
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
                "PublicationDate desc&$top=10000&$skip=0",
                status.HTTP_200_OK,
            ),
        ],
        indirect=["fastapi_app"],
        ids=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p"],
    )
    @responses.activate
    def test_valid_datetime(self, client, mock_token_validation, endpoint, odata, expected_code):
        """Test used to group all combination of datetime values. Fixed, closed/open interval."""
        mock_token_validation()
        responses.add(responses.GET, odata, json={"value": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == expected_code

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, page, is_last",
        [
            ("/auxip/collections/s2_adgs2_AUX_OBMEMC/items?token=next:page=", "3", True),
            ("/auxip/collections/s2_adgs2_AUX_OBMEMC/items?token=next:page=", "1", False),
            ("/cadip/collections/cadip_session_by_id/items?token=next:page=", "3", True),
            ("/cadip/collections/cadip_session_by_id/items?token=next:page=", "1", False),
        ],
    )
    @responses.activate
    def test_token_in_url(
        self,
        client,
        mock_token_validation,
        adgs_response,
        cadip_session_response,
        endpoint,
        page,
        is_last,
    ):
        """Used to test if application correctly builds next/previous token."""
        mock_token_validation()
        base_cadip_uri = (
            "http://127.0.0.1:5000/Sessions?$filter=SessionId eq 'S1A_20200105072204051312'"
            "&$orderby=PublicationDate desc&"
            f"$top=10&$skip={(int(page) - 1) * 10}"
        )
        base_cadip_files_uri = (
            "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051312'&$top=1000&$skip=0"
        )
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
            json={"value": []} if is_last else cadip_session_response,
            status=200,
        )
        responses.add(responses.GET, base_cadip_files_uri, json={"value": []}, status=200)
        responses.add(responses.GET, base_adgs_uri, json={"value": []} if is_last else adgs_response, status=200)

        response = client.get(endpoint + page)
        assert response.status_code == status.HTTP_200_OK

        next_url = f"{str(response.url).split('token', maxsplit=1)[0]}token=next:page={str(int(page) + 1)}"
        prev_url = f"{str(response.url).split('token', maxsplit=1)[0]}token=prev:page={str(int(page) - 1)}"
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
                },
            ),
        ],
        indirect=["fastapi_app"],
    )
    def test_valid_collection_request(
        self,
        client,
        mock_token_validation,
        endpoint,
        odata_request,
        href,
        cadip_session_response,
        adgs_response,
    ):
        """Test a valid call to /collections endpoint, check that found collection is converted to a item link."""
        mock_token_validation()
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
                    "href": "https://scihub.copernicus.eu/twiki/pub/SciHubWebPortal/TermsConditions/"
                    "Sentinel_Data_Terms_and_Conditions.pdf",
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
                    "href": "https://scihub.copernicus.eu/twiki/pub/SciHubWebPortal/TermsConditions/"
                    "Sentinel_Data_Terms_and_Conditions.pdf",
                    "rel": "license",
                    "title": "Legal notice on the use of Copernicus Sentinel Data and Service Information",
                },
            ),
        ],
    )
    def test_valid_empty_collection(self, client, mock_token_validation, endpoint, odata_request, self_href):
        """Test when response from pickup is empty, the result should still be 200 oK,
        and contain a link to the license."""
        mock_token_validation()
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
    mock_token_validation,
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

    mock_token_validation(service)
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
    collection = service_utils.read_conf()["collections"][0]
    collection = deepcopy(collection)  # copy the cached response before we modify it
    collection.pop("id")
    collection.pop("query")

    #
    # Mock a collection with no hardcoded query, another with single values, another with multiple values

    if adgs:
        query2 = {
            "productType": "type1",
            "platformShortName": "sentinel-1",
        }
        query3 = {
            "productType": "type1, type2",
            "platformShortName": "sentinel-1, sentinel-2",
        }
    elif cadip:
        query2 = {
            "Satellite": "S1A",
        }
        query3 = {
            "Satellite": "S1A, S2A",
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
    user_ids = "id1, id2"
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
            #  - sortBy (https://pforge-exchange2.astrium.eads.net/jira/browse/RSPY-131)

            if adgs:
                uid = user_ids.split(",", maxsplit=1)[0]
                odata_no_query = (
                    "http://127.0.0.1:5000/Products?$filter="
                    f"contains(Name, '{uid}') and "
                    "PublicationDate gte {date_min} and PublicationDate lte {date_max}"
                    "&$orderby=PublicationDate%20asc&$top=10000&$skip=0&$expand=Attributes"
                )
                odata_query = (
                    "http://127.0.0.1:5000/Products?$filter="
                    f"contains(Name, '{uid}') and "
                    "PublicationDate gte {date_min} and PublicationDate lte {date_max} "
                    "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
                    "and att/OData.CSC.StringAttribute/Value eq '{product_type}') "
                    "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'platformShortName' "
                    "and att/OData.CSC.StringAttribute/Value eq '{constellation}')"
                    "&$orderby=PublicationDate%20asc&$top=10000&$skip=0&$expand=Attributes"
                )
            elif cadip:
                # Add quote to the user_id
                user_ids_with_quote = ", ".join([f"'{user_id}'" for user_id in user_ids.split(", ")])
                odata_no_query = (
                    "http://127.0.0.1:5000/Sessions?$filter="
                    f"SessionId in ({user_ids_with_quote}) "
                    "and PublicationDate gte {date_min} and PublicationDate lte {date_max}"
                    "&$orderby=PublicationDate%20asc&$top=10000&$skip=0"
                )

                odata_query = (
                    "http://127.0.0.1:5000/Sessions?$filter="
                    f"SessionId in ({user_ids_with_quote}) "
                    "and Satellite {satellite_op} {satellite} "
                    "and PublicationDate gte {date_min} and PublicationDate lte {date_max}"
                    "&$orderby=PublicationDate%20asc&$top=10000&$skip=0"
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
                if user_query:
                    odata = None
                else:
                    odata = odata_query
                date_min = user_datetime.split("/", maxsplit=1)[0]  # intersection between user and hardcoded datetimes
                date_max = hardcoded_date.split("/")[1]
                product_type = collection["query"].get("productType")
                constellation = collection["query"].get("platformShortName")
                satellite = collection["query"].get("Satellite", "")
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
                    satellite = user_satellite
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
                    if "," in satellite:
                        sats = ", ".join([f"'{sat}'" for sat in satellite.split(", ")])
                        satellite = f"({sats})"
                    else:
                        satellite = f"'{satellite}'"
                    odata = odata.format(
                        date_min=date_min,
                        date_max=date_max,
                        product_type=product_type,
                        constellation=constellation,
                        satellite=satellite,
                        satellite_op="in" if "," in satellite else "eq",
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
                assert response.is_success
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


@pytest.mark.parametrize(
    "fastapi_app, service",
    [(ROUTER_PREFIX_AUXIP, "adgs")],
    ids=["adgs"],
    indirect=["fastapi_app"],
)
def test_search_all_collections(
    mocker,
    mock_token_validation,
    client,
    service,
    adgs_response,
):
    """Test searching all collections at the same time."""
    mock_token_validation(service)
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
            "http://127.0.0.1:5000/Products?$orderby=PublicationDate desc&$top=10000&$skip=0&$expand=Attributes",
            status=status.HTTP_200_OK,
            json=adgs_response,
        )

        # Search all collections at the same time
        url = f"{os.getenv('router_prefix')}/search"
        response = client.get(url)

        # We have mocked the same response for all n collections,
        # so we should have n calls to the search function a single result.
        assert response.is_success
        features = response.json()["features"]
        assert spy_search.call_count == collection_count
        assert len(spy_search.spy_return) == len(features) == 1
