"""Docstring to be added."""
import filecmp
import os
import os.path as osp
import time
from contextlib import contextmanager

import pytest
import responses
from fastapi.testclient import TestClient

from rs_server.CADIP.cadip_backend import app
from rs_server.CADIP.models.cadu_download_status import (
    CaduDownloadStatus,
    EDownloadStatus,
)
from rs_server.db.database import get_db

# Resource folders specified from the parent directory of this current script
RSC_FOLDER = osp.realpath(osp.join(osp.dirname(__file__), "resources"))
S3_FOLDER = osp.join(RSC_FOLDER, "s3")
ENDPOINTS_FOLDER = osp.join(RSC_FOLDER, "endpoints")

"""
TC-001 : User1 sends a CURL request to a CADIP backend Server on
URL /cadip/{station}/cadu?name=”xxx”&local="pathXXXX". He receives a download start status.
The download continues in background. After few minutes, the file is stored on the local disk.'
"""


@pytest.mark.unit
@responses.activate
def test_valid_endpoint_request(database):  # pylint: disable=unused-argument
    """Test the behavior of a valid endpoint request for CADIP CADU download.

    This unit test checks the behavior of the CADIP CADU download endpoint when provided with
    valid parameters. It simulates the download process, verifies the status code, and checks
    the content of the downloaded file.

    Args:
        database: The database fixture for the test.

    Returns:
        None

    Raises:
        AssertionError: If the test fails to assert the expected outcomes.
    """
    download_dir = "/tmp"
    filename = "CADIP_test_file_eodag.raw"
    cadu_id = "id_1"
    publication_date = "2023-10-10T00:00:00.111Z"

    endpoint = f"/cadip/CADIP/cadu?cadu_id=id_1&name={filename}"

    with contextmanager(get_db)() as db:
        # Add a download status to database
        CaduDownloadStatus.get_or_create(
            db=db,
            cadu_id=cadu_id,
            name=filename,
            available_at_station=publication_date,
            status=EDownloadStatus.IN_PROGRESS,
        )
        responses.add(
            responses.GET,
            "http://127.0.0.1:5000/Files(id_1)/$value",
            body="some byte-array data\n",
            status=200,
        )
        client = TestClient(app)
        # send the request
        data = client.get(endpoint)
        # let the file to be copied local
        time.sleep(1)
        try:
            assert data.status_code == 200
            # test file content
            assert filecmp.cmp(
                os.path.join(download_dir, filename),
                os.path.join(ENDPOINTS_FOLDER, "CADIP_test_file.raw"),
            )
            # clean downloaded file
        finally:
            os.remove(os.path.join(download_dir, filename))
