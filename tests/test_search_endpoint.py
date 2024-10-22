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

import pytest
import responses
import yaml
from fastapi import HTTPException, status
from pydantic import ValidationError
from rs_server_adgs.adgs_utils import auxip_map_mission
from rs_server_cadip.cadip_utils import cadip_map_mission

# pylint: disable=too-few-public-methods, too-many-arguments


@pytest.mark.unit
@responses.activate
def test_valid_search_by_session_id(expected_products, client, mock_token_validation):
    """Test used for searching a file by a given session id or ids."""
    # Test with no parameters
    assert client.get("/cadip/cadip/cadu/search").status_code == status.HTTP_400_BAD_REQUEST
    mock_token_validation("cadip")
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Files?$filter="SessionID%20eq%20session_id1"&$top=1000',
        json={"responses": expected_products[0]},
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
        'http://127.0.0.1:5000/Files?$filter="SessionID%20in%20session_id2,%20session_id3"&$top=1000',
        json={"responses": expected_products[1:]},
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
        'http://127.0.0.1:5000/Files?$filter="SessionID%20eq%20session_id2%20and%20PublicationDate%20gt%20'
        '2022-01-01T12:00:00.000Z%20and%20PublicationDate%20lt%202023-12-30T12:00:00.000Z"&$top=1000',
        json={"responses": expected_products},
        status=200,
    )
    endpoint = "/cadip/CADIP/cadu/search?datetime=2022-01-01T12:00:00Z/2023-12-30T12:00:00Z&session_id=session_id2"
    assert client.get(endpoint).status_code == status.HTTP_200_OK


#########################
# Reworked tests section
#########################


class TestOperatorDefinedCollections:
    """Class used to group tests for operator-defined collections."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, code",
        [
            ("/cadip/collections/cadip_session_incomplete/items", status.HTTP_400_BAD_REQUEST),
            ("/cadip/collections/cadip_session_incomplete_no_stop/items", status.HTTP_400_BAD_REQUEST),
            ("/cadip/collections/cadip_session_incomplete_no_start/items", status.HTTP_400_BAD_REQUEST),
            ("/auxip/collections/adgs_invalid/items", status.HTTP_400_BAD_REQUEST),
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
            # if both plaftorm and const are defined, priority is to get constellation since it contanis more results
            ("sentinel-1a", "sentinel-1", "S1A, S1B, S1C"),
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
        ],
    )
    def test_invalid_cadip_mapping(self, platform, constellation):
        """Pytest using only invalid inputs, output is not verified, function should raise exception."""
        with pytest.raises(HTTPException):
            cadip_map_mission(platform, constellation)


class TestSearchEndpoints:
    """Class used to group search endpoints tests."""

    def test_cadip_search(self):
        """CADIP search tests to be implemented here"""

    def test_adgs_search(self):
        """ADGS search tests to be implemented here"""


class TestLandingPagesEndpoints:
    """Class for landing page tests."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, collection_link",
        [("/cadip", "/cadip/collections"), ("/auxip", "/auxip/collections")],
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

        # The result should be 2 empty lists.
        empty_response = client.get(endpoint).json()
        assert {"type": "Object", "links": [], "collections": []} == empty_response

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
        "endpoint, title, expected_queryables",
        [
            ("/cadip/queryables", "Queryables for CADIP Search API", ["Satellite", "PublicationDate"]),
            ("/auxip/queryables", "Queryables for ADGS Search API", ["platformShortName", "PublicationDate"]),
        ],
    )
    def test_general_queryables(self, client, endpoint, title, expected_queryables):
        """Endpoint to test all queryables."""
        resp = client.get(endpoint).json()
        assert resp["title"] == title
        for queryable in expected_queryables:
            assert queryable in resp["properties"].keys()

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint, expected_queryables",
        [
            ("/cadip/collections/cadip_session_by_id_list/queryables", ["Satellite", "PublicationDate"]),
            ("/auxip/collections/adgs_by_platform/queryables", ["PublicationDate", "platformSerialIdentifier"]),
        ],
    )
    def test_collection_queryables(self, client, endpoint, expected_queryables):
        """Endpoint to test specific collection queryables."""
        resp = client.get(endpoint).json()
        for queryable in expected_queryables:
            assert queryable in resp["properties"].keys()


class TestModelValidationError:
    """Class used to group tests for error when validating."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        [
            "/cadip/search?collection=cadip_session_by_id_list",
            "/cadip/search/items?collection=cadip_session_by_id_list",
            "/cadip/collections/cadip_session_by_id_list",
            "/cadip/collections/cadip_session_by_id_list/items",
            "/cadip/collections/cadip_session_by_id_list/items/sessionId",
        ],
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
        "endpoint",
        [
            "/auxip/collections/adgs_by_platform",
            "/auxip/collections/adgs_by_platform/items",
            "/auxip/collections/adgs_by_platform/items/sessionId",
        ],
    )
    def test_adgs_validation_errors(self, client, mocker, endpoint):
        """Test used to mock a validation error on pydantic model, should return HTTP 422."""
        mocker.patch(
            "rs_server_adgs.api.adgs_search.process_product_search",
            side_effect=ValidationError.from_exception_data("Invalid data", line_errors=[]),
        )
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestErrorWhileBuildUpCollection:
    """Class used to group tests for error when processing."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        ["/cadip/search?collection=cadip_session_by_id_list", "/cadip/collections/cadip_session_by_id_list"],
    )
    def test_cadip_collection_creation_failure(self, client, mocker, endpoint):
        """Test used to generate a KeyError while Collection is created, should return HTTP 422."""
        mocker.patch("rs_server_cadip.api.cadip_search.process_session_search", side_effect=KeyError)
        assert client.get(endpoint).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "endpoint",
        ["/auxip/search?collection=adgs_by_platform", "/auxip/collections/adgs_by_platform"],
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
    def test_cadip_feature_mapping(self, client, mock_token_validation, cadip_feature, cadip_response):
        """Test a cadip pickup response with 2 assets is correctly mapped to a stac Feature
        Visit conftest to view content of cadip_feature and cadip_response.
        """
        # Mock pickup response and token validation
        mock_token_validation()
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Sessions?$filter=%22SessionId%20eq%20S1A_20200105072204051312%22&$top=20&"
            "$expand=Files",
            json=cadip_response,
            status=200,
        )
        response = client.get("/cadip/collections/cadip_session_by_id/items/S1A_20200105072204051312").json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response == cadip_feature, "Features doesn't match"

    @pytest.mark.unit
    @responses.activate
    def test_cadip_empty_feature_mapping(self, client, mock_token_validation, cadip_feature):
        """Test to verify the output of rs-server when pick-up point response is empty."""
        mock_token_validation()
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Sessions?$filter=%22SessionId%20eq%20S1A_20200105072204051312%22&$top=20&"
            "$expand=Files",
            json={"responses": []},
            status=200,
        )
        response = client.get("/cadip/collections/cadip_session_by_id/items/S1A_20200105072204051312")
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response.json() != cadip_feature, "Features doesn't match"
        assert response.json()["detail"] == "Session S1A_20200105072204051312 not found."
        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.unit
    @responses.activate
    def test_adgs_feature_mapping(self, client, mock_token_validation, adgs_feature, adgs_response):
        """Test mapping of an adgs reponse with expanded attributes"""
        mock_token_validation()
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att/Name%20"
            "eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'AUX_OBMEMC')%22&$top=1000"
            "&$expand=Attributes",
            json=adgs_response,
            status=200,
        )
        response = client.get(
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items/S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
        ).json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response == adgs_feature, "Features doesn't match"

    @pytest.mark.unit
    @responses.activate
    def test_adgs_empty_feature_mapping(self, client, mock_token_validation, adgs_feature):
        """Test to verify the output of rs-server when pick-up point response is empty."""
        mock_token_validation()
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att/Name%20"
            "eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'AUX_OBMEMC')%22&$top=1000"
            "&$expand=Attributes",
            json={"responses": []},
            status=200,
        )
        response = client.get(
            "/auxip/collections/s2_adgs2_AUX_OBMEMC/items/S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
        )
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response.json() != adgs_feature, "Features doesn't match"
        assert (
            response.json()["detail"] == "AUXIP S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF not found."
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
                "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att/Name%20"
                "eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'AUX_OBMEMC')%22&$top=1000"
                "&$expand=Attributes",
                {"detail": "AUXIP INVALID_ITEM not found."},
            ),
            (
                "/cadip/collections/cadip_session_by_id/items/INVALID_ITEM",
                "http://127.0.0.1:5000/Sessions?$filter=%22SessionId%20eq%20S1A_20200105072204051312%22&"
                "$top=20&$expand=Files",
                {"detail": "Session INVALID_ITEM not found."},
            ),
        ],
    )
    def test_invalid_item_mapping(
        self,
        client,
        mock_token_validation,
        cadip_response,
        adgs_response,
        endpoint,
        odata_url,
        detail,
    ):
        """Test to verify the output of rs-server when given collection is valid and item is invalid."""
        mock_token_validation()
        responses.add(
            responses.GET,
            odata_url,
            json=self.setup("adgs" if "auxip" in endpoint else "cadip", cadip_response, adgs_response),
            status=200,
        )
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == detail


class TestFeatureCollectionOdataStacMapping:
    """Class that group unittests for /*/collections/{collection-id}/items mapping from odata to stac."""

    @pytest.mark.unit
    @responses.activate
    def test_cadip_feature_collection_mapping(self, client, mock_token_validation, cadip_feature, cadip_response):
        """Test a cadip pickup response with 2 assets is correctly mapped to a stac Feature
        Visit conftest to view content of cadip_feature and cadip_response.
        """
        # Mock pickup response and token validation
        mock_token_validation()
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Sessions?$filter=%22SessionId%20eq%20S1A_20200105072204051312%22&$top=20&"
            "$expand=Files",
            json=cadip_response,
            status=200,
        )
        response = client.get("/cadip/collections/cadip_session_by_id/items").json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response == {"type": "FeatureCollection", "features": [cadip_feature]}, "Features doesn't match"

    @pytest.mark.unit
    @responses.activate
    def test_adgs_feature_collection_mapping(self, client, mock_token_validation, adgs_feature, adgs_response):
        """Test mapping of an adgs reponse with expanded attributes"""
        mock_token_validation()
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att/Name%20"
            "eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'AUX_OBMEMC')%22&$top=1000"
            "&$expand=Attributes",
            json=adgs_response,
            status=200,
        )
        response = client.get("/auxip/collections/s2_adgs2_AUX_OBMEMC/items").json()
        # Assert that receive odata response is correctly mapped to stac feature.
        assert response == {"type": "FeatureCollection", "features": [adgs_feature]}, "Features doesn't match"

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
        "endpoint, odata_request, href",
        [
            (
                "/cadip/collections/cadip_session_by_id",
                "http://127.0.0.1:5000/Sessions?$filter=%22SessionId%20eq%20S1A_20200105072204051312%22&"
                "$top=20&$expand=Files",
                {"href": "./simple-item.json", "rel": "item", "title": "S1A_20200105072204051312"},
            ),
            (
                "/auxip/collections/s2_adgs2_AUX_OBMEMC",
                "http://127.0.0.1:5000/Products?$filter=%22Attributes/OData.CSC.StringAttribute/any(att:att"
                "/Name%20eq%20'productType'%20and%20att/OData.CSC.StringAttribute/Value%20eq%20'AUX_OBMEMC')%22&"
                "$top=1000&$expand=Attributes",
                {
                    "href": "./simple-item.json",
                    "rel": "item",
                    "title": "S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
                },
            ),
        ],
    )
    def test_valid_collection_request(
        self,
        client,
        mock_token_validation,
        endpoint,
        odata_request,
        href,
        cadip_response,
        adgs_response,
    ):
        """Test a valid call to /collections endpoint, check that found collection is converted to a item link."""
        mock_token_validation()
        selected_response = self.setup("adgs" if "auxip" in endpoint else "cadip", cadip_response, adgs_response)
        responses.add(responses.GET, odata_request, json=selected_response, status=200)
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_200_OK
        assert href in response.json()["links"]

    @pytest.mark.unit
    @responses.activate
    @pytest.mark.parametrize(
        "endpoint, odata_request, href, self_href",
        [
            (
                "/cadip/collections/cadip_session_by_id",
                "http://127.0.0.1:5000/Sessions?$filter=%22SessionId%20eq%20S1A_20200105072204051312%22&$top=20&"
                "$expand=Files",
                {"href": "./simple-item.json", "rel": "item", "title": "S1A_20200105072204051312"},
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
                    "href": "./simple-item.json",
                    "rel": "item",
                    "title": "S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
                },
                {
                    "href": "https://scihub.copernicus.eu/twiki/pub/SciHubWebPortal/TermsConditions/"
                    "Sentinel_Data_Terms_and_Conditions.pdf",
                    "rel": "license",
                    "title": "Legal notice on the use of Copernicus Sentinel Data and Service Information",
                },
            ),
        ],
    )
    def test_valid_empty_collection(self, client, mock_token_validation, endpoint, odata_request, href, self_href):
        """Test when response from pickup is empty, the result should still be 200 oK,
        but with no other links than self references"""
        mock_token_validation()
        responses.add(responses.GET, odata_request, json={"responses": []}, status=200)
        response = client.get(endpoint)
        assert response.status_code == status.HTTP_200_OK
        assert href not in response.json()["links"]
        assert response.json()["links"][0] == self_href
