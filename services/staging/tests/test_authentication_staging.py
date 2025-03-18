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

"""Test staging endpoint authentication."""

import pytest
from pytest_httpx import HTTPXMock
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.pytest.pytest_authentication_utils import (
    VALID_APIKEY_HEADER,
    WRONG_APIKEY_HEADER,
    init_test,
)
from rs_server_staging.main import app, must_be_authenticated
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from .resources.sample_data import sample_process_metadata_model


@pytest.mark.unit
def test_auth_roles(mocker, staging_client_auth):
    """
    Validate role-based access control for the 'staging' resource.

    This test verifies that:
    - A client with the necessary roles can access 'staging' resource endpoints.
    - Unauthorized access is denied for other resources ('other_staging').

    Test Cases:
    1. Ensure that a client with valid roles for 'staging' can:
       - Retrieve process details.
       - Start an execution process (to be updated for JSON body).
       - Retrieve job details.
       - Delete a job.
       - Fetch job results.

    2. Mock database behavior to allocate a job to 'staging' and validate access.

    3. Change the resource to 'other_staging' and verify that:
       - Unauthorized requests return HTTP 401 with the appropriate error message.
       - Database mock reflects a job allocated to 'other_staging' and denies access accordingly.

    Notes:
    - Some assertions for execution processes are commented out and need JSON body updates.
    - Mocking is used to simulate database interactions for job allocation.
    """
    resource = "staging"
    assert staging_client_auth.get(f"/processes/{resource}").status_code != HTTP_401_UNAUTHORIZED

    # Use json body here, to be updated
    # assert staging_client_auth.post(f"/processes/{resource}/execution").status_code != HTTP_401_UNAUTHORIZED

    mock_db_table = mocker.MagicMock()
    # Mock the job databse to allocate staging resource for this job-id
    mock_db_table.get_job.return_value = {"process_id": resource}
    mocker.patch.object(staging_client_auth.app, "extra", {"process_manager": mock_db_table})
    job_id = "job_id"
    assert staging_client_auth.get(f"/jobs/{job_id}").status_code != HTTP_401_UNAUTHORIZED
    assert staging_client_auth.delete(f"/jobs/{job_id}").status_code != HTTP_401_UNAUTHORIZED
    assert staging_client_auth.get(f"/jobs/{job_id}/results").status_code != HTTP_401_UNAUTHORIZED

    # When setting resource to other value, check that UAC does not allow since roles are not updated.
    resource = "other_staging"
    unauthorized_resource_process_response = staging_client_auth.get(f"/processes/{resource}")
    assert unauthorized_resource_process_response.status_code == HTTP_401_UNAUTHORIZED
    assert unauthorized_resource_process_response.json() == {
        "message": "Missing RS_PROCESSES_OTHER_STAGING_READ authorization role",
    }

    # Use json body here, to be updated
    # assert staging_client_auth.post(f"/processes/{resource}/execution").status_code == HTTP_401_UNAUTHORIZED

    # Mock the jobs db, to allocate current job-id to other_staging resource.
    mock_db_table.get_job.return_value = {"process_id": resource}
    mocker.patch.object(staging_client_auth.app, "extra", {"process_manager": mock_db_table})
    unauthorized_resource_jobs_response = staging_client_auth.get(f"/jobs/{job_id}")
    assert unauthorized_resource_jobs_response.status_code == HTTP_401_UNAUTHORIZED
    assert unauthorized_resource_jobs_response.json() == {
        "message": "Missing RS_PROCESSES_OTHER_STAGING_READ authorization role",
    }

    unauthorized_resource_jobs_result_response = staging_client_auth.get(f"/jobs/{job_id}/results")
    assert unauthorized_resource_jobs_result_response.status_code == HTTP_401_UNAUTHORIZED
    assert unauthorized_resource_jobs_result_response.json() == {
        "message": "Missing RS_PROCESSES_OTHER_STAGING_READ authorization role",
    }

    unauthorized_resource_jobs_response_delete = staging_client_auth.delete(f"/jobs/{job_id}")
    assert unauthorized_resource_jobs_response_delete.status_code == HTTP_401_UNAUTHORIZED
    assert unauthorized_resource_jobs_response_delete.json() == {
        "message": "Missing RS_PROCESSES_OTHER_STAGING_DISMISS authorization role",
    }


logger = Logging.default(__name__)


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
@pytest.mark.parametrize("test_apikey", [True, False], ids=["test_apikey", "no_apikey"])
@pytest.mark.parametrize("test_oauth2", [True, False], ids=["test_oauth2", "no_oauth2"])
async def test_error_when_not_authenticated(mocker, staging_client, httpx_mock: HTTPXMock, test_apikey, test_oauth2):
    """
    Test that all the http endpoints are protected and return 401 or 403 if not authenticated.
    """
    owner_id = "pyteam"
    await init_test(
        mocker,
        httpx_mock,
        staging_client,
        test_apikey,
        test_oauth2,
        [],
        mock_wrong_apikey=True,
        user_login=owner_id,
    )
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # For each route and method from the openapi specification i.e. with the /processes/ and /jobs/ prefixes
    for path, methods in app.openapi()["paths"].items():
        if not must_be_authenticated(path):
            continue
        for method in methods.keys():

            # JSON data for POST endpoitns
            json_data = {}
            if path == "/processes/{resource}/execution":
                json_data = sample_process_metadata_model

            # Format the endpoint values
            endpoint = path.format(resource="staging", job_id="job_id")
            logger.debug(f"Test the {endpoint!r} [{method}] authentication")

            # With a valid apikey or oauth2 authentication, we should have a status code != 401 or 403.
            # We have other errors on many endpoints because we didn't give the right arguments,
            # but it's OK it is not what we are testing here.
            if test_apikey or test_oauth2:
                response = staging_client.request(method, endpoint, json=json_data, **header)
                logger.debug(response)
                assert response.status_code not in (
                    HTTP_401_UNAUTHORIZED,
                    HTTP_403_FORBIDDEN,
                    HTTP_422_UNPROCESSABLE_ENTITY,  # with 422, the authentication is not called and not tested
                )

                # With a wrong apikey, we should have a 403 error
                if test_apikey:
                    assert (
                        staging_client.request(method, endpoint, **WRONG_APIKEY_HEADER).status_code
                        == HTTP_403_FORBIDDEN
                    )

            # Check that without authentication, the endpoint is protected and we receive a 401
            else:
                assert staging_client.request(method, endpoint).status_code == HTTP_401_UNAUTHORIZED


def test_authenticated_endpoints():
    """Test that the catalog endpoints need authentication."""
    for route_path in ["/api", "/api.html", "/health", "/_mgmt/ping"]:
        assert not must_be_authenticated(route_path)
    for route_path in [
        "/processes",
        "/processes/{resource}",
        "/processes/{resource}/execution",
        "/jobs/{job_id}",
        "/jobs",
        "/jobs/{job_id}/results",
        "/staging/dask/auth",
    ]:
        assert must_be_authenticated(route_path)
