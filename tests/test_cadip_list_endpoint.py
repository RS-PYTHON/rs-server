"""Docstring to be added."""
import pytest
from fastapi.testclient import TestClient

from src.CADIP.cadip_backend import app


# TC-001 : User1 send a CURL request to a CADIP-Server on URL /cadip/{station}/cadu/list .
# He receives the list of CADU in the interval.
@pytest.mark.unit
@pytest.mark.parametrize(
    "expected_chunk, expected_chunk_id, expected_chunk_name",
    [
        (0, "2b17b57d-fff4-4645-b539-91f305c27c69", "DCS_01_S1A_20170501121534062343_ch1_DSDB_00001.raw"),
        (1, "some_id_2", "S1A.raw"),
        (2, "some_id_3", "S2L1C.raw"),
    ],
)
def test_endpoint(expected_chunk, expected_chunk_id, expected_chunk_name):
    """Docstring to be added."""
    # Get all products between 2014 - 2023
    start_date = "2014-01-01T12:00:00.000Z"
    stop_date = "2023-12-30T12:00:00.000Z"
    cadip_test_station = "CADIP"
    rs_url = f"/cadip/{cadip_test_station}/cadu/list"
    endpoint = f'{rs_url}?start_date="{start_date}"&stop_date="{stop_date}"'
    client = TestClient(app)
    # convert output to python dict
    data = eval(client.get(endpoint).content.decode())
    # check that request returned more than 1 element
    assert len(data[cadip_test_station])
    # Check if ids and names are matching with given parameters
    assert data[cadip_test_station][expected_chunk] == [expected_chunk_id, expected_chunk_name]
