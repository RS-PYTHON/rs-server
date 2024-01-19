"""Unittests for cadip search endpoint."""
from contextlib import contextmanager

import pytest
import responses
from fastapi import status
from rs_server_common.db.database import get_db


def create_rs_list_cadu(station: str, start: str, stop: str):
    """Create an rs-server endpoint for searching CADU products based on start date, stop date, and station.

    Parameters
    ----------
    station : str
        The station name used in the request.
    start : str
        The start date for the request.
    stop : str
        The stop date for the request.

    Returns
    -------
    str: The generated rs-server endpoint.
    """
    rs_url = f"/cadip/{station}/cadu/search"
    # Create rs-server endpoint
    return f"{rs_url}?start_date={start}&stop_date={stop}"


# TC-001 : User1 send a CURL request to a CADIP-Server on URL /cadip/{station}/cadu/list .
# He receives the list of CADU in the interval.
@pytest.mark.unit
@responses.activate
def test_valid_endpoint_request_list(expected_products, client):
    """Test case for retrieving products from the CADIP station between 2014 and 2023.

    This test sends a request to the CADIP station's endpoint for products within the specified date range.
    It checks if the response contains more than one element and verifies that the IDs and names match
    with the expected parameters.
    """
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Files?$filter="PublicationDate gt 2014-01-01T12:00:00.000Z and PublicationDate lt '
        '2023-12-30T12:00:00.000Z"',
        json={"responses": expected_products},
        status=200,
    )
    # Get all products between 2014 - 2023 from "CADIP" station
    endpoint = create_rs_list_cadu("CADIP", "2014-01-01T12:00:00.000Z", "2023-12-30T12:00:00.000Z")
    with contextmanager(get_db)():
        # TODO, query and test db status
        # send request and convert output to python dict
        data = client.get(endpoint).json()

        # check that request returned more than 1 element
        assert len(data["CADIP"]) == len(expected_products)
        # Check if ids and names are matching with given parameters
        assert any("some_id_2" in product for product in data["CADIP"])
        assert any("some_id_3" in product for product in data["CADIP"])


@pytest.mark.unit
@responses.activate
def test_invalid_endpoint_request(client):
    """Test case for validating the behavior of the endpoint when an invalid request is made.

    This test activates the 'responses' library to mock a successful response with an empty list.
    It then sends a request to the specified endpoint with date parameters, expecting an empty list in the response.
    """
    cadip_json_resp: dict = {"responses": []}
    responses.add(
        responses.GET,
        'http://127.0.0.1:5000/Files?$filter="PublicationDate gt 2023-01-01T12:00:00.000Z and PublicationDate lt '
        '2024-12-30T12:00:00.000Z"',
        json=cadip_json_resp,
        status=200,
    )
    # Get all products from 2023 to 2024, this request should result in a empty list since there are no matches
    endpoint = create_rs_list_cadu("CADIP", "2023-01-01T12:00:00.000Z", "2024-12-30T12:00:00.000Z")
    with contextmanager(get_db)():
        # convert output to python dict
        data = client.get(endpoint).json()
        # check that request returned no elements
        assert len(data["CADIP"]) == 0


@pytest.mark.unit
def test_invalid_endpoint_param_missing_start_stop(client):
    """Test case for validating the behavior of the endpoint when the stop date is missing.

    This test sends a request to the specified endpoint without providing a stop date,
    expecting a 400 Bad Request response.
    """
    # Test without a stop date, this should result in a 400 bad request response.
    start_date = "2023-01-01T12:00:00.000Z"
    cadip_test_station = "CADIP"
    rs_url = f"/cadip/{cadip_test_station}/cadu/search"
    endpoint = f"{rs_url}?start_date={start_date}"
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    # Test with a start / stop date that is not matching format.
    endpoint = create_rs_list_cadu("CADIP", "2014-01-01", "2023-12-30T12:00:00.000Z")
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    endpoint = create_rs_list_cadu("CADIP", "2023-01-01T12:00:00.000Z", "2025-12")
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.unit
def test_invalid_endpoint_param_station(client):
    """Test case for validating the behavior of the endpoint when an incorrect station name is provided.

    This test sends a request to the specified endpoint with an incorrect station name,
    expecting a 400 Bad Request response.
    """
    # Test with and inccorect station name, this should result in a 400 bad request response.
    endpoint = create_rs_list_cadu("incorrect_station", "2023-01-01T12:00:00.000Z", "2024-12-30T12:00:00.000Z")
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
