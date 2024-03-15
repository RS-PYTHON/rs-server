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
                    "datetime": "N/A",
                    "start_datetime": "N/A",
                    "end_datetime": "N/A",
                    "eviction_datetime": "eviction_date_test_value",
                    "cadip:id": "2b17b57d-fff4-4645-b539-91f305c27c69",
                    "cadip:retransfer": False,
                    "cadip:final_block": True,
                    "cadip:block_number": "BlockNumber_test_value",
                    "cadip:channel": "Channel_test_value",
                    "cadip:session_id": "session_id_test_value",
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
