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

"""Unit tests for the authentication."""

import pytest
from pytest_httpx import HTTPXMock
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.pytest.pytest_authentication_utils import (
    VALID_APIKEY_HEADER,
    WRONG_APIKEY_HEADER,
    init_test,
)
from rs_server_staging.main import app, must_be_authenticated
from rs_server_staging.processors import Staging
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from .resources.sample_data import sample_process_metadata_model

logger = Logging.default(__name__)


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
@pytest.mark.parametrize("test_apikey", [True, False], ids=["test_apikey", "no_apikey"])
@pytest.mark.parametrize("test_oauth2", [True, False], ids=["test_oauth2", "no_oauth2"])
async def test_error_when_not_authenticated(  # pylint: disable=too-many-locals
    mocker,
    staging_client,
    staging_instance: Staging,
    client,
    httpx_mock: HTTPXMock,
    test_apikey,
    test_oauth2,
):
    """
    Test that all the http endpoints are protected and return 401 or 403 if not authenticated.
    """
    owner_id = "pyteam"
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

    # Also test the processor rights
    collection = "test_collection"
    station_id = "station_id"
    role = f"RS_PROCESSES_STAGING_DOWNLOAD_{station_id}"
    error_auth = f"Loading station token service failed: 401: Missing {role.upper()} authorization role"
    mocker.patch.object(staging_instance, "assets_info", new="some_asset")
    mock_load = mocker.Mock()
    mock_load.station_id = station_id
    mocker.patch("rs_server_staging.processors.load_external_auth_config_by_domain", return_value=mock_load)
    mocker.patch.object(staging_instance, "prepare_streaming_tasks", return_value=True)
    mocker.patch.object(staging_instance, "dask_cluster_connect", return_value=client)
    mock_request = mocker.Mock()
    mocker.patch.object(staging_instance, "request", new=mock_request)
    spy_log_job = mocker.spy(staging_instance, "log_job_execution")

    # Without the right role, we should have an unauthorized error
    mock_request.state.auth_roles = []
    await staging_instance.process_rspy_features(collection)
    assert spy_log_job.call_args[0][2] == error_auth
    # With the righ role, it should fail for whatever other reason
    # (because we didn't mock the right values, but it's OK it is not what we are testing here)
    spy_log_job.reset_mock()
    mock_request.state.auth_roles = [role]
    await staging_instance.process_rspy_features(collection)
    assert spy_log_job.call_args[0][2] != error_auth


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
