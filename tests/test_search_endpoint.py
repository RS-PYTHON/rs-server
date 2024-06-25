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

"""Unittests for cadip search endpoint."""

from contextlib import contextmanager

import pytest
import responses
import sqlalchemy
from fastapi import HTTPException, status
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.db.database import get_db
from rs_server_common.db.models.download_status import EDownloadStatus

from .conftest import (  # pylint: disable=no-name-in-module
    expected_sessions_builder_fixture,
)


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
                    "created": "2021-02-16T12:00:00.000Z",
                    "datetime": "1970-01-01T12:00:00.000Z",
                    "start_datetime": "1970-01-01T12:00:00.000Z",
                    "end_datetime": "1970-01-01T12:00:00.000Z",
                    "eviction_datetime": "eviction_date_test_value",
                    "cadip:id": "2b17b57d-fff4-4645-b539-91f305c27c69",
                    "cadip:retransfer": False,
                    "cadip:final_block": True,
                    "cadip:block_number": "BlockNumber_test_value",
                    "cadip:channel": "Channel_test_value",
                    "cadip:session_id": "session_id1",
                },
                "links": [],
                "assets": {"file": {"file:size": "size_test_value"}},
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
                    "created": "2021-02-16T12:00:00.000Z",
                    "adgs:id": "2b17b57d-fff4-4645-b539-91f305c27c69",
                    "datetime": "ContentDate_Start_test_value",
                    "start_datetime": "ContentDate_Start_test_value",
                    "end_datetime": "ContentDate_End_test_value",
                },
                "links": [],
                "assets": {"file": {"file:size": "ContentLength_test_value"}},
            },
            ["datetime", "adgs:id"],
        ),
    ],
)
def test_valid_endpoint_request_list(
    expected_products,
    client,
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
def test_invalid_endpoint_request(client, station, endpoint, start, stop):
    """Test case for validating the behavior of the endpoint when an invalid request is made.

    This test activates the 'responses' library to mock a successful response with an empty list.
    It then sends a request to the specified endpoint with date parameters, expecting an empty list in the response.
    """
    # Register ADGS / CADIP responses
    cadip_json_resp: dict = {"responses": []}
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
        print(data)
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
    # Test with and inccorect station name, this should result in a 400 bad request response.
    station = "incorrect_station"
    endpoint = f"/cadip/{station}/cadu/search?datetime=2023-01-01T12:00:00Z/2024-12-30T12:00:00Z"
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.unit
@pytest.mark.parametrize(
    "endpoint, start, stop",
    [
        ("/cadip/CADIP/cadu/search", "2014-01-01T12:00:00Z", "2023-12-30T12:00:00Z"),
        ("/adgs/aux/search", "2023-01-01T12:00:00Z", "2024-12-30T12:00:00Z"),
    ],
)
def test_failure_while_creating_retriever(mocker, client, endpoint, start, stop):
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
        test_endpoint = f"{endpoint}&limit={limit}"
        data = client.get(test_endpoint).json()
        # check features number, and numberMatched / numberReturned
        assert len(data["features"]) == limit
        assert data["numberMatched"] == limit
        assert data["numberReturned"] == limit
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
            "/cadip/cadip/session?id=S1A_20170501121534062343,S1A_20240328185208053186",
            '"SessionId%20in%20S1A_20170501121534062343,%20S1A_20240328185208053186"&$top=20&$expand=Files',
            ["S1A_20170501121534062343", "S1A_20240328185208053186"],
            ["2017-05-01T12:00:00", "2024-03-28T18:52:26Z"],
            ["S1A", "S1A"],
        ),
        # TC001: Search one session only with a single id (ex: id=S1A_20240312192515052953).
        # Check that response return 1 result in STAC format for the given id.
        (
            "/cadip/cadip/session?id=S1A_20240328185208053186",
            '"SessionId%20eq%20S1A_20240328185208053186"&$top=20&$expand=Files',
            "S1A_20240328185208053186",
            "2024-03-28T18:52:26Z",
            "S1A",
        ),
        # Test with a single platform
        (
            "/cadip/cadip/session?id=S1A_20240328185208053186&platform=S1A",
            "%22SessionId%20eq%20S1A_20240328185208053186%20and%20Satellite%20in%20S1A%22&$top=20&$expand=Files",
            "S1A_20240328185208053186",
            "2024-03-28T18:52:26Z",
            "S1A",
        ),
        # Test with a list of session ids and list of platforms
        (
            "/cadip/cadip/session?id=S1A_20240328185208053186,S1A_20240328185208053186&platform=S1A,S2B",
            "%22SessionId%20in%20S1A_20240328185208053186,%20S1A_20240328185208053186%20and%20Satellite%20in%20S1A,"
            "%20S2B%22&$top=20&$expand=Files"
            "",
            ["S1A_20240328185208053186", "S1A_20240328185208053186"],
            ["2024-03-28T18:52:26Z", "2024-03-28T18:52:26Z"],
            ["S1A", "S2B"],
        ),
        # Test only with a list of platforms
        (
            "/cadip/cadip/session?platform=S1A, S2B",
            "%22Satellite%20in%20S1A,%20%20S2B%22&$top=20&$expand=Files",
            ["S1A_20240328185208053186", "S1A_20240328185208053186"],
            ["2024-03-28T18:52:26Z", "2024-03-28T18:52:26Z"],
            ["S1A", "S2B"],
        ),
        # # TC002: Search several sessions by satellites and date
        # # (ex: platform=S1A,S1B&start_date=2024-03-12T08:00:00.000Z&stop_date=2024-03-12T12:00:00.000Z.)
        # # Check that response returns several results in STAC format for the sessions that match the criteria
        (
            "/cadip/cadip/session?start_date=2020-02-16T12:00:00Z&stop_date=2023-02-16T12:00:00Z&platform=S1A",
            "%22Satellite%20in%20S1A%20and%20PublicationDate%20gt%202020-02-16T12:00:00.000Z%20and%20PublicationDate"
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
    ],
)
@responses.activate
def test_valid_sessions_endpoint_request_list(
    client,
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
    # Mock EODAG request to pickup-point
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
    assert response.json()["numberMatched"] == len(sessions_response)
    assert response.json()["features"]


@pytest.mark.unit
def test_invalid_sessions_endpoint_request(client):
    """Test cases with invalid requests send to /session endpoint"""
    # Test with missing all parameters
    assert client.get("/cadip/cadip/session").status_code == status.HTTP_400_BAD_REQUEST
    # Test only with start, without stop
    assert client.get("/cadip/cadip/session?start_date=2020-02-16T12:00:00Z").status_code == status.HTTP_400_BAD_REQUEST
    assert client.get("/cadip/cadip/session?stop_date=2020-02-16T12:00:00Z").status_code == status.HTTP_400_BAD_REQUEST
    # Test with platform and only start_date, should work since platform=S1A is valid
    assert (
        client.get("/cadip/cadip/session?platform=S1A&start_date=2020-02-16T12:00:00Z").status_code
        != status.HTTP_400_BAD_REQUEST
    )


@pytest.mark.unit
@responses.activate
def test_valid_search_by_session_id(expected_products, client):
    """Test used for searching a file by a given session id or ids."""
    # Test with no parameters
    assert client.get("/cadip/cadip/cadu/search").status_code == status.HTTP_400_BAD_REQUEST

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
            "%22Satellite%20in%20S2B%22&$top=20&$expand=Files",
            "cadip/cadip/session?platform=S2B",
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
                "numberMatched": 1,
                "numberReturned": 1,
                "features": [
                    {
                        "stac_version": "1.0.0",
                        "stac_extensions": ["https://stac-extensions.github.io/timestamps/v1.1.0/schema.json"],
                        "type": "Feature",
                        "id": "S2B_20231117033237234567",
                        "geometry": None,
                        "properties": {
                            "start_datetime": "2023-11-17T06:05:37.234Z",
                            "datetime": "2023-11-17T06:05:37.234Z",
                            "end_datetime": "2023-11-17T06:15:37.234Z",
                            "published": "2023-11-17T06:15:37.234Z",
                            "platform": "S2B",
                            "cadip:id": "3f8d5c2e-a9b1-4d6f-87ce-1a240b9d5e72",
                            "cadip:num_channels": 2,
                            "cadip:station_unit_id": "01",
                            "cadip:downlink_orbit": 53186,
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
                        "assets": [
                            {
                                "DCS_01_S2B_20231117170332034987_ch2_DSDB_00001.raw": {
                                    "cadip:id": "axd19d2f-29eb-4c18-bc1f-bf2769a3a16d",
                                    "cadip:retransfer": False,
                                    "cadip:final_block": False,
                                    "cadip:block_number": 1,
                                    "cadip:channel": 1,
                                    "cadip:session_id": "S2B_20231117033237234567",
                                    "created": "2023-11-17T18:52:29.165Z",
                                    "eviction_datetime": "2023-11-17T18:52:29.165Z",
                                    "file:size": "42",
                                    "roles": ["cadu"],
                                    "href": "http://testserver/cadip/cadip/cadu?name=DCS_01_S2B_20231117170332034987_ch"
                                    "2_DSDB_00001.raw",
                                },
                            },
                            {
                                "DCS_01_S2B_20231117170332034987_ch2_DSDB_00002.raw": {
                                    "cadip:id": "a9c84e5d-3fbc-4a7d-8b2e-6d135c9e8af1",
                                    "cadip:retransfer": False,
                                    "cadip:final_block": False,
                                    "cadip:block_number": 1,
                                    "cadip:channel": 1,
                                    "cadip:session_id": "S2B_20231117033237234567",
                                    "created": "2023-11-17T18:52:39.165Z",
                                    "eviction_datetime": "2023-11-17T18:52:39.165Z",
                                    "file:size": "42",
                                    "roles": ["cadu"],
                                    # Note: 127.0.0.1:8000 replaced with testserver due to TestClient usage
                                    "href": "http://testserver/cadip/cadip/cadu?name=DCS_01_S2B_20231117170332034987_ch"
                                    "2_DSDB_00002.raw",
                                },
                            },
                        ],
                    },
                ],
            },
        ),
        (
            '"Satellite%20in%20incorrect_platform"&$top=20&$expand=Files',
            "/cadip/cadip/session?platform=incorrect_platform",
            {},
            {"type": "FeatureCollection", "numberMatched": 0, "numberReturned": 0, "features": []},
        ),
    ],
)
@responses.activate
def test_expanded_sessions_endpoint_request(
    client,
    odata_request,
    rs_server_request,
    odata_response,
    rs_server_response,
):
    """Test cases on how rs-server process the sessions responses that contains multiple assets

    Nominal: Test that an OData response with two files is mapped to a STAC response with two assets
    Degraded: Test that an OData response with an empty Files list is mapped to a STAC response with an empty asset list
    Degraded: Test that an OData response with a Files list set to null is mapped to a STAC response with an empty asset
     list
    Degraded: Test that an OData response without a Files element is mapped to a STAC response with an empty asset list

    """
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
