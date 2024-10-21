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
from contextlib import contextmanager

import pytest
import responses
import sqlalchemy
import yaml
from fastapi import HTTPException, status
from pydantic import ValidationError
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_adgs.adgs_utils import auxip_map_mission
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_cadip.cadip_utils import cadip_map_mission
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.db.database import get_db
from rs_server_common.db.models.download_status import EDownloadStatus

from .conftest import (  # pylint: disable=no-name-in-module
    expected_sessions_builder_fixture,
)

# pylint: disable=too-many-lines, too-many-arguments


# TC-001 : User1 send a CURL request to a CADIP-Server on URL /cadip/{station}/cadu/list .
# He receives the list of CADU in the interval.
@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize(
    "endpoint, db_handler, expected_feature, fields_to_sort",
    [
        (
            "/cadip/CADIP/cadu/search?datetime=2014-01-01T12:00:00Z/2023-12-30T12:00:00Z",
            CadipDownloadStatus,
            {
                "stac_version": "1.0.0",
                "stac_extensions": ["https://stac-extensions.github.io/file/v2.1.0/schema.json"],
                "type": "Feature",
                "id": "DCS_01_S1A_20170501121534062343_ch1_DSDB_00001.raw",
                "geometry": None,
                "properties": {
                    "created": "2021-02-16T12:00:00Z",
                    "datetime": "1970-01-01T12:00:00Z",
                    "start_datetime": "1970-01-01T12:00:00Z",
                    "end_datetime": "1970-01-01T12:00:00Z",
                    "eviction_datetime": "eviction_date_test_value",
                    "cadip:id": "2b17b57d-fff4-4645-b539-91f305c27c69",
                    "cadip:retransfer": False,
                    "cadip:final_block": True,
                    "cadip:block_number": "BlockNumber_test_value",
                    "cadip:channel": "Channel_test_value",
                    "cadip:session_id": "session_id1",
                },
                "links": [],
                "assets": {"file": {"href": "not_set", "file:size": "size_test_value"}},
            },
            ["datetime", "cadip:id"],
        ),
        (
            "/adgs/aux/search?datetime=2014-01-01T12:00:00Z/2023-12-30T12:00:00Z",
            AdgsDownloadStatus,
            {
                "stac_version": "1.0.0",
                "stac_extensions": ["https://stac-extensions.github.io/file/v2.1.0/schema.json"],
                "type": "Feature",
                "id": "DCS_01_S1A_20170501121534062343_ch1_DSDB_00001.raw",
                "geometry": None,
                "properties": {
                    "created": "2021-02-16T12:00:00Z",
                    "adgs:id": "2b17b57d-fff4-4645-b539-91f305c27c69",
                    "datetime": "1970-01-01T12:00:00Z",
                    "start_datetime": "1970-01-01T12:00:00Z",
                    "end_datetime": "1970-01-01T12:00:00Z",
                },
                "links": [],
                "assets": {"file": {"href": "not_set", "file:size": "size_test_value"}},
            },
            ["datetime", "adgs:id"],
        ),
    ],
)
def test_valid_endpoint_request_list(
    expected_products,
    client,
    mock_token_validation,
    endpoint,
    db_handler,
    expected_feature,
    fields_to_sort,
):  # pylint: disable=too-many-arguments
    """Test case for retrieving products from the CADIP station between 2014 and 2023.

    This test sends a request to the CADIP station's endpoint for products within the specified date range.
    It checks if the response contains more than one element and verifies that the IDs and names match
    with the expected parameters.
    """
    mock_token_validation()
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Files?$filter="PublicationDate gt 2014-01-01T12:00:00.000Z and PublicationDate lt '
        '2023-12-30T12:00:00.000Z"&$top=1000',
        json={"responses": expected_products},
        status=200,
    )
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Products?$filter="PublicationDate gt 2014-01-01T12:00:00.000Z and PublicationDate lt '
        '2023-12-30T12:00:00.000Z"&$top=1000',
        json={"responses": expected_products},
        status=200,
    )
    # Get all products between 2014 - 2023 from "CADIP" and "ADGS" station
    with contextmanager(get_db)() as db:
        with pytest.raises(HTTPException):
            # Check that product is not in database, this should raise HTTPException
            db_handler.get(db, name="S2L1C.raw")
            assert False
        features = client.get(endpoint).json()["features"]
        # check that request returned more than 1 element
        assert len(features) == len(expected_products)
        # Check if ids and names are matching with given parameters
        assert any("some_id_2" in product["properties"].values() for product in features)
        assert any("some_id_3" in product["properties"].values() for product in features)
        assert db_handler.get(db, name="S2L1C.raw").status == EDownloadStatus.NOT_STARTED
        assert expected_feature in features

        # Assert that the features are sorted by descending datetime by default
        sorted_features = sorted(features, key=lambda feature: feature["properties"]["datetime"], reverse=True)
        assert features == sorted_features

        # For each field on which to sort
        for field_to_sort in fields_to_sort:
            # Sort in ascending and descending order
            for reverse in [False, True]:
                # Call the endpoint again, but this time by sorting results
                sign = "-" if reverse else "+"
                features = client.get(endpoint, params={"sortby": f"{sign}{field_to_sort}"}).json()["features"]

                # Assert that the features are sorted
                sorted_features = sorted(
                    features,
                    key=lambda feature, field=field_to_sort: feature["properties"][field],  # type: ignore
                    reverse=reverse,
                )
                assert features == sorted_features


@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize(
    "station, endpoint, start, stop",
    [
        ("CADIP", "/cadip/CADIP/cadu/search", "2023-01-01T12:00:00Z", "2024-12-30T12:00:00Z"),
        ("AUX", "/adgs/aux/search", "2023-01-01T12:00:00Z", "2024-12-30T12:00:00Z"),
    ],
)
def test_invalid_endpoint_request(
    client,
    mock_token_validation,
    station,
    endpoint,
    start,
    stop,
):  # pylint: disable=too-many-arguments
    """Test case for validating the behavior of the endpoint when an invalid request is made.

    This test activates the 'responses' library to mock a successful response with an empty list.
    It then sends a request to the specified endpoint with date parameters, expecting an empty list in the response.
    """
    # Register ADGS / CADIP responses
    cadip_json_resp: dict = {"responses": []}
    mock_token_validation()
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Files?$filter="PublicationDate gt 2023-01-01T12:00:00.000Z and PublicationDate lt '
        '2024-12-30T12:00:00.000Z"&$top=1000',
        json=cadip_json_resp,
        status=200,
    )

    adgs_json_resp: dict = {"responses": []}
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Products?$filter="PublicationDate gt 2023-01-01T12:00:00.000Z and PublicationDate lt '
        '2024-12-30T12:00:00.000Z"&$top=1000',
        json=adgs_json_resp,
        status=200,
    )
    # Get all products from 2023 to 2024, this request should result in a empty list since there are no matches
    test_endpoint = f"{endpoint}?datetime={start}/{stop}&station={station}"
    with contextmanager(get_db)():
        # convert output to python dict
        data = client.get(test_endpoint).json()
        # check that request returned no elements
        assert len(data["features"]) == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, start_date, stop_date",
    [
        ("/cadip/CADIP/cadu/search", "2014-01-01", "2023-12-30T12:00:00Z"),
        ("/cadip/CADIP/cadu/search", "2023-01-01T12:00:00Z", "2025-12"),
        ("/adgs/aux/search", "2014-01-01", "2023-12-30T12:00:00Z"),
        ("/adgs/aux/search", "2023-01-01T12:00:00Z", "2025-12"),
    ],
)
def test_invalid_endpoint_param_missing_start_stop(client, endpoint, start_date, stop_date):
    """Test endpoint with missing start/stop query params.

    This test calls the /data endpoint without passing the required
    start and stop query parameters. It verifies that a 400 error
    is returned in this case.

    Args:
        client: The test client fixture

    Returns:
        None

    Raises:
        None
    """
    # Test an endpoint with missing stop date, should raise 422, unprocessable
    unprocessable_endpoint = f"{endpoint}?datetime={start_date}"
    response = client.get(unprocessable_endpoint)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    # Test an endpoint with an incorrect format for start / stop date, should raise 400 bad request
    search_endpoint = f"{endpoint}?datetime={start_date}/{stop_date}"
    response = client.get(search_endpoint)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# This test is specific only to CADIP Station
@pytest.mark.unit
def test_invalid_endpoint_param_station(client):
    """Test case for validating the behavior of the endpoint when an incorrect station name is provided.

    This test sends a request to the specified endpoint with an incorrect station name,
    expecting a 400 Bad Request response.
    """
    # Test with and incorrect station name, this should result in a 404 not found request response.
    endpoint = "/cadip_session_incorrect_station/collections/correct_collection/items"
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, start, stop",
    [
        ("/cadip/CADIP/cadu/search", "2014-01-01T12:00:00Z", "2023-12-30T12:00:00Z"),
        ("/adgs/aux/search", "2023-01-01T12:00:00Z", "2024-12-30T12:00:00Z"),
    ],
)
def test_failure_while_creating_retriever(
    mocker,
    mock_token_validation,
    client,
    endpoint,
    start,
    stop,
):  # pylint: disable=too-many-arguments
    """
    Tests the failure response of the ADGS / CADIP product search endpoint due to retriever creation errors.

    This unit test verifies the response of the ADGS / CADIP product search endpoint when there's a failure
    in creating the ADGS / CADIP data retriever. It covers two scenarios:
    1. When the retriever creation fails due to an invalid station, expecting a 400 Bad Request response.
    2. When there is a SQL operational error during product preparation, also expecting a 400 Bad Request response.

    @param mocker: The pytest-mock fixture for mocking dependencies.
    @param client: The FastAPI test client for making HTTP requests.
    Step for second fixture:
    - Mocks 'init_adgs_retriever' to raise 'CreateProviderFailed' with a specific error message.
    - Sends a GET request to the '/adgs/aux/search' endpoint and asserts that the status code is 400.
    - Then, mocks 'prepare_products' to raise 'sqlalchemy.exc.OperationalError'.
    - Again, sends a GET request to the same endpoint and asserts that the status code is 400.
    """
    # Mock this function to raise an error
    mock_token_validation()
    mocker.patch(
        "rs_server_adgs.api.adgs_search.init_adgs_provider",
        side_effect=CreateProviderFailed("Invalid station"),
    )
    mocker.patch(
        "rs_server_cadip.api.cadip_search.init_cadip_provider",
        side_effect=CreateProviderFailed("Invalid station"),
    )
    test_endpoint = f"{endpoint}?datetime={start}/{stop}"
    # Check that request status is 400
    data = client.get(test_endpoint)
    assert data.status_code == 400
    # Mock a sql connection error
    mocker.patch(
        "rs_server_common.utils.utils.write_search_products_to_db",
        side_effect=sqlalchemy.exc.OperationalError,
    )
    # Check that request status is 400
    data = client.get(test_endpoint)
    assert data.status_code == 400


@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize(
    "endpoint, db_handler, limit",
    [
        ("/cadip/CADIP/cadu/search?datetime=2014-01-01T12:00:00Z/2023-12-30T12:00:00Z", CadipDownloadStatus, 3),
        ("/adgs/aux/search?datetime=2014-01-01T12:00:00Z/2023-12-30T12:00:00Z", AdgsDownloadStatus, 1),
    ],
)
def test_valid_pagination_options(expected_products, client, endpoint, db_handler, limit):
    """Test case for retrieving products from the CADIP station between 2014 and 2023.

    This test sends a request to the CADIP station's endpoint for products within the specified date range.
    It checks if the response contains more than one element and verifies that the IDs and names match
    with the expected parameters.
    """
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Files?$filter="PublicationDate gt 2014-01-01T12:00:00.000Z and PublicationDate lt '
        '2023-12-30T12:00:00.000Z"&$top=3',
        json={"responses": expected_products[:limit]},
        status=200,
    )
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Products?$filter="PublicationDate gt 2014-01-01T12:00:00.000Z and PublicationDate lt '
        '2023-12-30T12:00:00.000Z"&$top=1',
        json={"responses": expected_products[:limit]},
        status=200,
    )
    # Get all products between 2014 - 2023 from "CADIP" and "ADGS" station
    with contextmanager(get_db)() as db:
        with pytest.raises(HTTPException):
            # Check that product is not in database, this should raise HTTPException
            db_handler.get(db, name="S2L1C.raw")
            assert False
        # Check negative, should raise 422
        limit = 0
        test_endpoint = f"{endpoint}&limit={limit}"
        assert client.get(test_endpoint).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        limit = -5
        test_endpoint = f"{endpoint}&limit={limit}"
        assert client.get(test_endpoint).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# TEST SESSIONS ZONE


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, pickup_point_translated_filter, expected_session_id, expected_publication_date, expected_platform",
    [
        # Test with a list of 2 SessionIds
        (
            "/cadip/collections/cadip_session_by_id_list/items",
            '"SessionId%20in%20S1A_20170501121534062343,%20S1A_20240328185208053186"&$top=20&$expand=Files',
            ["S1A_20170501121534062343", "S1A_20240328185208053186"],
            ["2017-05-01T12:00:00", "2024-03-28T18:52:26Z"],
            ["S1A", "S1A"],
        ),
        # TC001: Search one session only with a single id (ex: id=S1A_20240312192515052953).
        # Check that response return 1 result in STAC format for the given id.
        (
            "/cadip/collections/cadip_session_by_id/items",
            '"SessionId%20eq%20S1A_20240328185208053186"&$top=20&$expand=Files',
            "S1A_20240328185208053186",
            "2024-03-28T18:52:26Z",
            "S1A",
        ),
        # Test with a single platform
        (
            "/cadip/collections/cadip_session_by_id_platform/items",
            "%22SessionId%20eq%20S1A_20240328185208053186%20and%20Satellite%20eq%20S1A%22&$top=20&$expand=Files",
            "S1A_20240328185208053186",
            "2024-03-28T18:52:26Z",
            "S1A",
        ),
        # Test with a list of session ids and list of platforms
        (
            "/cadip/collections/cadip_session_by_lists_id_platform/items",
            "%22SessionId%20in%20S1A_20240328185208053186,%20S1A_20240328185208053186%20and%20Satellite%20in%20S1A,"
            "%20S2B%22&$top=20&$expand=Files"
            "",
            ["S1A_20240328185208053186", "S1A_20240328185208053186"],
            ["2024-03-28T18:52:26Z", "2024-03-28T18:52:26Z"],
            ["S1A", "S2B"],
        ),
        # Test only with a list of platforms
        (
            "/cadip/collections/cadip_session_by_platform_list/items",
            "%22Satellite%20in%20S1A,%20S2B%22&$top=20&$expand=Files",
            ["S1A_20240328185208053186", "S1A_20240328185208053186"],
            ["2024-03-28T18:52:26Z", "2024-03-28T18:52:26Z"],
            ["S1A", "S2B"],
        ),
        # # TC002: Search several sessions by satellites and date
        # # (ex: platform=S1A,S1B&start_date=2024-03-12T08:00:00.000Z&stop_date=2024-03-12T12:00:00.000Z.)
        # # Check that response returns several results in STAC format for the sessions that match the criteria
        (
            "/cadip/collections/cadip_session_by_start_stop_platform/items",
            "%22Satellite%20eq%20S1A%20and%20PublicationDate%20gt%202020-02-16T12:00:00.000Z%20and%20PublicationDate"
            "%20lt%202023-02-16T12:00:00.000Z%22&$top=20&$expand=Files",
            ["S1A_20240328185208053186", "S1A_20240328185208053186", "S1A_20240329083700053194"],
            ["2024-03-28T18:52:26Z", "2024-03-28T18:52:26Z", "2024-03-29T08:37:22Z"],
            ["S1A", "S1A", "S2B"],
        ),
        (
            "/cadip/search/items?collection=cadip_session_by_start_stop_platform",
            "%22Satellite%20eq%20S1A%20and%20PublicationDate%20gt%202020-02-16T12:00:00.000Z%20and%20PublicationDate"
            "%20lt%202023-02-16T12:00:00.000Z%22&$top=20&$expand=Files",
            ["S1A_20240328185208053186", "S1A_20240328185208053186", "S1A_20240329083700053194"],
            ["2024-03-28T18:52:26Z", "2024-03-28T18:52:26Z", "2024-03-29T08:37:22Z"],
            ["S1A", "S1A", "S2B"],
        ),
    ],
    ids=[
        "list_id",
        "single_id",
        "single_id_single_platform",
        "list_id_list_platform",
        "list_platform",
        "start_stop_single_platform",
        "search_items",
    ],
)
@responses.activate
def test_valid_sessions_endpoint_request_list(
    client,
    mock_token_validation,
    endpoint,
    pickup_point_translated_filter,
    expected_session_id,
    expected_publication_date,
    expected_platform,
):  # pylint: disable=too-many-arguments
    """Test cases for all valid endpoints requests of cadip session endpoint"""
    # Note: All translated endpoints have been tested with simulators (rs-testmeans)
    # Build the session result content with expected values
    sessions_response = expected_sessions_builder_fixture(
        expected_session_id,
        expected_publication_date,
        expected_platform,
    )
    mock_token_validation("cadip")
    # Mock EODAG request to pickup-point as well as the token
    responses.add(
        responses.GET,
        f"http://127.0.0.1:5000/Sessions?$filter={pickup_point_translated_filter}",
        json={"responses": sessions_response},
        status=200,
    )
    # Test that eodag correctly translates given endpoint to translated endpoint
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_200_OK
    # Test that OData (dict) is translated to STAC.
    assert response.json()["features"]


@pytest.mark.unit
def test_invalid_sessions_endpoint_request(client, mocker):
    """Test cases with invalid requests send to /session endpoint"""
    # Mock the env var RSPY_USE_MODULE_FOR_STATION_TOKEN to True. This will trigger the
    # usage of the internal token module  for getting the token and setting it to the eodag
    mocker.patch("rs_server_common.authentication.authentication_to_external.env_bool", return_value=True)
    # Test with missing all parameters
    assert client.get("/cadip/collections/cadip_session_incomplete/items").status_code == status.HTTP_400_BAD_REQUEST
    # Test only with start, without stop
    assert (
        client.get("/cadip/collections/cadip_session_incomplete_no_stop/items").status_code
        == status.HTTP_400_BAD_REQUEST
    )
    assert (
        client.get("/cadip/collections/cadip_session_incomplete_no_start/items").status_code
        == status.HTTP_400_BAD_REQUEST
    )
    # Test with platform and only start_date, should work since platform=S1A is valid
    assert (
        client.get("/cadip/collections/cadip_session_incomplete_platf_no_start/items").status_code
        != status.HTTP_400_BAD_REQUEST
    )


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


@pytest.mark.parametrize(
    "odata_request, rs_server_request, odata_response, rs_server_response",
    [
        (
            "%22Satellite%20eq%20S2B%22&$top=20&$expand=Files",
            "/cadip/collections/cadip_session_s2b/items",
            # Note: The following JSON were modified due to compliance of HTTP/1.1 protocol
            # "Retransfer": false -> "Retransfer": False,
            # "geometry": null -> "geometry": None,
            {
                "Id": "3f8d5c2e-a9b1-4d6f-87ce-1a240b9d5e72",
                "SessionId": "S2B_20231117033237234567",
                "NumChannels": 2,
                "PublicationDate": "2023-11-17T06:15:37.234Z",
                "Satellite": "S2B",
                "StationUnitId": "01",
                "DownlinkOrbit": 53186,
                "AcquisitionId": "53186_1",
                "AntennaId": "MSP21",
                "FrontEndId": "01",
                "Retransfer": False,
                "AntennaStatusOK": True,
                "FrontEndStatusOK": True,
                "PlannedDataStart": "2023-11-17T06:05:37.234Z",
                "PlannedDataStop": "2023-11-17T06:15:37.234Z",
                "DownlinkStart": "2023-11-17T06:05:37.234Z",
                "DownlinkStop": "2023-11-17T06:15:37.234Z",
                "DownlinkStatusOK": True,
                "DeliveryPushOK": True,
                "Files": [
                    {
                        "Id": "axd19d2f-29eb-4c18-bc1f-bf2769a3a16d",
                        "Name": "DCS_01_S2B_20231117170332034987_ch2_DSDB_00001.raw",
                        "SessionID": "S2B_20231117033237234567",
                        "Channel": 1,
                        "BlockNumber": 1,
                        "FinalBlock": False,
                        "PublicationDate": "2023-11-17T18:52:29.165Z",
                        "EvictionDate": "2023-11-17T18:52:29.165Z",
                        "Size": "42",
                        "Retransfer": False,
                    },
                    {
                        "Id": "a9c84e5d-3fbc-4a7d-8b2e-6d135c9e8af1",
                        "Name": "DCS_01_S2B_20231117170332034987_ch2_DSDB_00002.raw",
                        "SessionID": "S2B_20231117033237234567",
                        "Channel": 1,
                        "BlockNumber": 1,
                        "FinalBlock": False,
                        "PublicationDate": "2023-11-17T18:52:39.165Z",
                        "EvictionDate": "2023-11-17T18:52:39.165Z",
                        "Size": "42",
                        "Retransfer": False,
                    },
                ],
            },
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "stac_version": "1.0.0",
                        "stac_extensions": ["https://stac-extensions.github.io/timestamps/v1.1.0/schema.json"],
                        "type": "Feature",
                        "id": "S2B_20231117033237234567",
                        "geometry": None,
                        "properties": {
                            "start_datetime": "2023-11-17T06:05:37.234000+00:00",
                            "datetime": "2023-11-17T06:05:37.234000+00:00",
                            "end_datetime": "2023-11-17T06:15:37.234000+00:00",
                            "published": "2023-11-17T06:15:37.234Z",
                            "platform": "S2B",
                            "cadip:id": "3f8d5c2e-a9b1-4d6f-87ce-1a240b9d5e72",
                            "cadip:num_channels": 2,
                            "cadip:station_unit_id": "01",
                            "sat:absolute_orbit": 53186,
                            "cadip:acquisition_id": 531861,
                            "cadip:antenna_id": "MSP21",
                            "cadip:front_end_id": "01",
                            "cadip:retransfer": False,
                            "cadip:antenna_status_ok": True,
                            "cadip:front_end_status_ok": True,
                            "cadip:planned_data_start": "2023-11-17T06:05:37.234Z",
                            "cadip:planned_data_stop": "2023-11-17T06:15:37.234Z",
                            "cadip:downlink_status_ok": True,
                            "cadip:delivery_push_ok": True,
                        },
                        "links": [],
                        "assets": {
                            "DCS_01_S2B_20231117170332034987_ch2_DSDB_00001.raw": {
                                "cadip:block_number": 1,
                                "cadip:channel": 1,
                                "cadip:final_block": False,
                                "cadip:id": "axd19d2f-29eb-4c18-bc1f-bf2769a3a16d",
                                "cadip:retransfer": False,
                                "cadip:session_id": "S2B_20231117033237234567",
                                "created": "2023-11-17T18:52:29.165Z",
                                "eviction_datetime": "2023-11-17T18:52:29.165Z",
                                "file:size": "42",
                                "href": "http://testserver/cadip/cadu?name=DCS_01_S2B_20231117170332034987_ch2_DSDB_"
                                "00001.raw",
                                "roles": [
                                    "cadu",
                                ],
                                "title": "DCS_01_S2B_20231117170332034987_ch2_DSDB_00001.raw",
                            },
                            "DCS_01_S2B_20231117170332034987_ch2_DSDB_00002.raw": {
                                "cadip:block_number": 1,
                                "cadip:channel": 1,
                                "cadip:final_block": False,
                                "cadip:id": "a9c84e5d-3fbc-4a7d-8b2e-6d135c9e8af1",
                                "cadip:retransfer": False,
                                "cadip:session_id": "S2B_20231117033237234567",
                                "created": "2023-11-17T18:52:39.165Z",
                                "eviction_datetime": "2023-11-17T18:52:39.165Z",
                                "file:size": "42",
                                "href": "http://testserver/cadip/cadu?name=DCS_01_S2B_20231117170332034987_ch2_DSDB_"
                                "00002.raw",
                                "roles": [
                                    "cadu",
                                ],
                                "title": "DCS_01_S2B_20231117170332034987_ch2_DSDB_00002.raw",
                            },
                        },
                    },
                ],
            },
        ),
        (
            '"Satellite%20in%20incorrect_platform"&$top=20&$expand=Files',
            "/cadip/collections/cadip_session_incorrect/items",
            {},
            {"type": "FeatureCollection", "features": []},
        ),
    ],
)
@responses.activate
def test_expanded_sessions_endpoint_request(
    client,
    mock_token_validation,
    odata_request,
    rs_server_request,
    odata_response,
    rs_server_response,
):  # pylint: disable=too-many-arguments
    """Test cases on how rs-server process the sessions responses that contains multiple assets

    Nominal: Test that an OData response with two files is mapped to a STAC response with two assets
    Degraded: Test that an OData response with an empty Files list is mapped to a STAC response with an empty asset list
    Degraded: Test that an OData response with a Files list set to null is mapped to a STAC response with an empty asset
     list
    Degraded: Test that an OData response without a Files element is mapped to a STAC response with an empty asset list

    Note: Assets are not expanded.
    """
    mock_token_validation("cadip")
    responses.add(
        responses.GET,
        f"http://127.0.0.1:5000/Sessions?$filter={odata_request}",
        json={"responses": odata_response},
        status=200,
    )
    response = client.get(rs_server_request)
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == rs_server_response
    # assert responses.assert_call_count(f"http://127.0.0.1:5000/Sessions?$filter={odata_request}", 1)


@pytest.mark.unit
@responses.activate
def test_cadip_collection(client, mock_token_validation):
    """Test the links from /station/collections/collection-id"""
    mock_token_validation("cadip")
    sid = "S1A_20240328185208053186"
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Sessions?$filter="Satellite%20in%20S1A"&$top=20&$expand=Files',
        json=expected_sessions_builder_fixture(sid, "2024-03-28T18:52:26Z", "S1A"),
        status=200,
    )

    response = client.get("/cadip/collections/cadip_session_by_satellite")
    assert response.status_code == status.HTTP_200_OK
    for link in response.json()["links"]:
        if link["rel"] == "item":
            assert sid in link["title"]


@pytest.mark.unit
@responses.activate
def test_invalid_cadip_collection(client, mock_token_validation):
    """Test cases with invalid requests/collections."""
    # Test a correctly configured collection with a bad query.
    mock_token_validation("cadip")
    response = client.get("/cadip/collections/cadip_session_incorrect")
    # Should return an empty collection, but with 200 status.
    assert response.status_code == status.HTTP_200_OK

    # Test that collection contains no "Item" links.
    assert not any("item" in link["rel"] for link in response.json()["links"])

    # Also check for root / self relation -> Disabled, should we manually ad root and self?
    # assert any("root" in link["rel"] for link in response.json()["links"])
    # assert any("self" in link["rel"] for link in response.json()["links"])

    # Test that a non existing collection return 404 with specific response.
    response = client.get("/cadip/collections/invalid_configured_collection")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "Unknown CADIP collection: 'invalid_configured_collection'"}

    # Test with a miss configured collection: cadip_session_incomplete does not define a Extent.
    response = client.get("/cadip/collections/cadip_session_incomplete")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


#########################
# Reworked tests section
#########################


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
    """Class that group unittests for /*/collections/{collection-id}/items/{item-id} mapping from odata to stac."""

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
