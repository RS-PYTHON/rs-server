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

"""Unittests for adgs status endpoint."""

from contextlib import contextmanager

import pytest
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.db.models.download_status import EDownloadStatus


@pytest.mark.unit
@pytest.mark.parametrize(
    "product_name, endpoint, db_handler",
    [
        ("some_aux_name", "/adgs/aux/status?name=some_aux_name", AdgsDownloadStatus),
        ("some_cadu_name", "/cadip/CADIP/cadu/status?name=some_cadu_name", CadipDownloadStatus),
    ],
)
def test_valid_status_request(client, product_name, endpoint, db_handler):
    """Test API endpoint response for valid status request.

    This test function will make a request to the /status endpoint
    and verify that the response has a 200 status code and the
    JSON response contains the expected keys.

    Args:
        client: The FastAPI test client to make requests

    Raises:
        AssertionError: If the response is not 200 or json does not have expected keys

    """
    with contextmanager(get_db)() as db:
        # Check status of product_name
        data = client.get(endpoint)
        # Verify that status is 404 (NOT_FOUND)
        assert data.status_code == 404
        # Insert aux_name into DB with status IN_PROGRESS
        db_handler.create(
            db=db,
            product_id="id_1",
            name=product_name,
            available_at_station="2023-12-30T12:00:00.000Z",
            status=EDownloadStatus.IN_PROGRESS,
        )
        # Check status
        data = client.get(endpoint)
        # Verify return status code, name and status
        assert data.status_code == 200
        assert data.json()["name"] == product_name
        assert EDownloadStatus(data.json()["status"]) == EDownloadStatus.IN_PROGRESS
