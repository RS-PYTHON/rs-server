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
from rs_server_common.utils.pytest.pytest_authentication_utils import (
    VALID_APIKEY_HEADER,
    init_test,
)
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_500_INTERNAL_SERVER_ERROR

from .resources.sample_data import sample_process_metadata_model


@pytest.mark.unit
@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
async def test_auth_roles(mocker, staging_client, httpx_mock: HTTPXMock):  # pylint: disable=too-many-locals
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
    owner_id = "pyteam"
    test_apikey = False
    test_oauth2 = True  # test only with the oauth2 cookie
    # pylint: disable=duplicate-code
    await init_test(
        mocker,
        httpx_mock,
        staging_client,
        test_apikey,
        test_oauth2,
        [
            "RS_PROCESSES_STAGING_READ",
            "RS_PROCESSES_STAGING_EXECUTE",
            "RS_PROCESSES_STAGING_DISMISS",
        ],
        mock_wrong_apikey=True,
        user_login=owner_id,
    )
    header = VALID_APIKEY_HEADER if test_apikey else {}

    resource = "staging"
    assert staging_client.get(f"/processes/{resource}", **header).status_code != HTTP_401_UNAUTHORIZED
    assert (
        staging_client.post(
            f"/processes/{resource}/execution",
            json=sample_process_metadata_model,
            **header,
        ).status_code
        != HTTP_401_UNAUTHORIZED
    )

    mock_db_table = mocker.MagicMock()
    # Mock the job databse to allocate staging resource for this job-id
    mock_db_table.get_job.return_value = {"processID": resource}
    mocker.patch.object(staging_client.app, "extra", {"process_manager": mock_db_table})
    job_id = "job_id"
    assert staging_client.get(f"/jobs/{job_id}", **header).status_code != HTTP_401_UNAUTHORIZED
    assert staging_client.delete(f"/jobs/{job_id}", **header).status_code != HTTP_401_UNAUTHORIZED
    assert staging_client.get(f"/jobs/{job_id}/results", **header).status_code != HTTP_401_UNAUTHORIZED

    # When setting resource to other value (corresponding to an existing resource),
    #  check that UAC does not allow since roles are not updated.
    resource = "other_staging"
    mock_resources = {
        "staging": {
            "id": "staging",
            "version": "0.0.1",
        },
        "other_staging": {
            "id": "staging",
            "version": "0.0.1",
        },
    }
    # Mock the existing resources
    mocker.patch.dict("rs_server_staging.main.api.config", {"resources": mock_resources})

    unauthorized_resource_process_response = staging_client.get(f"/processes/{resource}", **header)
    assert unauthorized_resource_process_response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert (
        "Missing RS_PROCESSES_OTHER_STAGING_READ authorization role"
        in unauthorized_resource_process_response.json()["detail"]
    )

    mocker.patch("rs_server_staging.main.validate_request", return_value={})
    unauthorized_execute_jobs_response = staging_client.post(
        f"/processes/{resource}/execution",
        json=sample_process_metadata_model,
        **header,
    )
    assert unauthorized_execute_jobs_response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert (
        "Missing RS_PROCESSES_OTHER_STAGING_EXECUTE authorization role"
        in unauthorized_execute_jobs_response.json()["detail"]
    )

    # Mock the jobs db, to allocate current job-id to other_staging resource.
    mock_db_table.get_job.return_value = {"processID": resource}
    mocker.patch.object(staging_client.app, "extra", {"process_manager": mock_db_table})
    unauthorized_resource_jobs_response = staging_client.get(f"/jobs/{job_id}", **header)
    assert unauthorized_resource_jobs_response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert (
        "Missing RS_PROCESSES_OTHER_STAGING_READ authorization role"
        in unauthorized_resource_jobs_response.json()["detail"]
    )

    unauthorized_resource_jobs_result_response = staging_client.get(f"/jobs/{job_id}/results", **header)
    assert unauthorized_resource_jobs_result_response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert (
        "Missing RS_PROCESSES_OTHER_STAGING_READ authorization role"
        in unauthorized_resource_jobs_result_response.json()["detail"]
    )

    unauthorized_resource_jobs_response_delete = staging_client.delete(f"/jobs/{job_id}", **header)
    assert unauthorized_resource_jobs_response_delete.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert (
        "Missing RS_PROCESSES_OTHER_STAGING_DISMISS authorization role"
        in unauthorized_resource_jobs_response_delete.json()["detail"]
    )
