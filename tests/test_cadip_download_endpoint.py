"""Docstring to be added."""
import filecmp
import os
import pdb
import time

import pytest
import responses
from contextlib import contextmanager
from fastapi import status
from fastapi.testclient import TestClient

from rs_server.CADIP.cadip_backend import app
from rs_server.CADIP.models.cadu_download_status import (
    CaduDownloadStatus,
    EDownloadStatus,
)
from rs_server.db.database import get_db


def create_rs_dwn_cadu(station: str, id: str, name: str, publication_date: str, local: str, obs: str):  # noqa: D417
    """Create an rs-server endpoint for download a CADU product.

    Parameters
    ----------
    station (str): The station name used in the request.
    start_date (str): The start date for the request.
    stop_date (str): The stop date for the request.

    Returns
    -------
    str: The generated rs-server endpoint.
    """    
    rs_url = f"/cadip/{station}/cadu"
    # Create rs-server endpoint
    print(f"{rs_url}?id={id}&name={name}&local={local}&publication_date={publication_date}")
    return f"{rs_url}?id={id}&name={name}&local={local}"


"""
TC-001 : User1 sends a CURL request to a CADIP backend Server on
URL /cadip/{station}/cadu?name=”xxx”&local="pathXXXX". He receives a download start status.
The download continues in background. After few minutes, the file is stored on the local disk.'
"""


@pytest.mark.unit
@responses.activate
def test_valid_endpoint_request(database):
    """Test case for retrieving products from the CADIP station between 2014 and 2023.

    This test sends a request to the CADIP station's endpoint for products within the specified date range.
    It checks if the response contains more than one element and verifies that the IDs and names match
    with the expected parameters.
    """
    responses.add(
        responses.GET,
        "http://127.0.0.1:5000/Files(2b17b57d-fff4-4645-b539-91f305c27c65)/$value",
        body="some byte-array data",
        status=200,
    )

    # download_dir = os.path.dirname(os.path.realpath(__file__))
    download_dir = "/tmp"
    download_file = "CADIP_test_file_eodag.raw"
    endpoint = create_rs_dwn_cadu("CADIP", "2b17b57d-fff4-4645-b539-91f305c27c65", 
                                  download_file, 
                                  download_dir,
                                  "2023-10-10T00:00:00.111Z",
                                  "s3://test-data/cadip/")
    # Open a database connection
    with contextmanager(get_db)() as db:
        client = TestClient(app)
        # send request
        data = client.get(endpoint)
        # let the file to be copied onto local
        time.sleep(1)
        assert data.status_code == 200
        # test file content
        assert filecmp.cmp(
            os.path.join(download_dir, download_file),
            os.path.join("./data", "CADIP_test_file.raw"),
        )
        # clean downloaded file
        os.remove(os.path.join(download_dir, download_file))
