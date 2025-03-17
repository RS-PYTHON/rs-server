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
from starlette.status import HTTP_401_UNAUTHORIZED


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
