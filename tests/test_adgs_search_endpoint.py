"""Unittests for adgs search endpoint."""
from contextlib import contextmanager

import pytest
import responses
import sqlalchemy
from fastapi import status
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.db.database import get_db


@pytest.mark.unit
@responses.activate
def test_valid_endpoint_request_list(expected_products, client):
    """
    Tests the successful retrieval and listing of products from the ADGS endpoint.

    This unit test validates the functionality of the ADGS product search endpoint for valid requests.
    It checks whether the endpoint correctly returns a list of products based on the specified start and stop dates.
    The test involves mocking an external service response and validating the endpoint's output.

    @param expected_products: A list of mock products expected to be returned in the response.
    @param client: The FastAPI test client for making HTTP requests.

    - Adds a mocked response for a GET request to an external service with a predefined query.
    - Sends a GET request to the '/adgs/aux/search' endpoint with specific start and stop times.
    - Asserts that the number of products returned in the response matches the expected number of mock products.
    - Further asserts that specific product IDs are present in the returned data, ensuring data integrity.
    """
    responses.add(
        responses.GET,
        'http://127.0.0.1:5001/Products?$filter="PublicationDate gt 2014-01-01T12:00:00.000Z and PublicationDate lt '
        '2023-12-30T12:00:00.000Z"',
        json={"responses": expected_products},
        status=200,
    )
    start_time = "2014-01-01T12:00:00.000Z"
    stop_time = "2023-12-30T12:00:00.000Z"
    endpoint = f"/adgs/aux/search?start_date={start_time}&stop_date={stop_time}"
    with contextmanager(get_db)():
        # TODO, query and test db status
        # send request and convert output to python dict
        data = client.get(endpoint).json()

        # check that request returned more than 1 element
        assert len(data["AUX"]) == len(expected_products)
        # Check if ids and names are matching with given parameters
        assert any("some_id_2" in product for product in data["AUX"])
        assert any("some_id_3" in product for product in data["AUX"])


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
        'http://127.0.0.1:5001/Products?$filter="PublicationDate gt 2023-01-01T12:00:00.000Z and PublicationDate lt '
        '2024-12-30T12:00:00.000Z"',
        json=cadip_json_resp,
        status=200,
    )
    # Get all products from 2023 to 2024, this request should result in a empty list since there are no matches
    start_time = "2023-01-01T12:00:00.000Z"
    stop_time = "2024-12-30T12:00:00.000Z"
    endpoint = f"/adgs/aux/search?start_date={start_time}&stop_date={stop_time}"
    with contextmanager(get_db)():
        # convert output to python dict
        data = client.get(endpoint).json()
        # check that request returned no elements
        assert len(data["AUX"]) == 0


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
    start_time = "2014-01-01"
    stop_time = "2023-12-30T12:00:00.000Z"
    endpoint = f"/adgs/aux/search?start_date={start_time}&stop_date={stop_time}"
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    start_time = "2023-01-01T12:00:00.000Z"
    stop_time = "2025-12"
    endpoint = f"/adgs/aux/search?start_date={start_time}&stop_date={stop_time}"
    response = client.get(endpoint)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.unit
def test_failure_while_creating_retriever(mocker, client):
    """
    Tests the failure response of the ADGS product search endpoint due to retriever creation errors.

    This unit test verifies the response of the ADGS product search endpoint when there's a failure
    in creating the ADGS data retriever. It covers two scenarios:
    1. When the retriever creation fails due to an invalid station, expecting a 400 Bad Request response.
    2. When there is a SQL operational error during product preparation, also expecting a 400 Bad Request response.

    @param mocker: The pytest-mock fixture for mocking dependencies.
    @param client: The FastAPI test client for making HTTP requests.

    - Mocks 'init_adgs_retriever' to raise 'CreateProviderFailed' with a specific error message.
    - Sends a GET request to the '/adgs/aux/search' endpoint and asserts that the status code is 400.
    - Then, mocks 'prepare_products' to raise 'sqlalchemy.exc.OperationalError'.
    - Again, sends a GET request to the same endpoint and asserts that the status code is 400.
    """
    # Mock this function to raise an error
    mocker.patch(
        "rs_server.ADGS.api.adgs_search.init_adgs_retriever",
        side_effect=CreateProviderFailed("Invalid station"),
    )
    start_time = "2014-01-01T12:00:00.000Z"
    stop_time = "2023-12-30T12:00:00.000Z"
    endpoint = f"/adgs/aux/search?start_date={start_time}&stop_date={stop_time}"
    # Check that request status is 400
    data = client.get(endpoint)
    assert data.status_code == 400
    # Mock a sql connection error
    mocker.patch("rs_server.api_common.utils.prepare_products", side_effect=sqlalchemy.exc.OperationalError)
    # Check that request status is 400
    data = client.get(endpoint)
    assert data.status_code == 400
