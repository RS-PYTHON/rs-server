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
"""Module use for osam endpoints tests"""
import threading

import pytest
from starlette.status import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)


@pytest.mark.unit
def test_ping_endpoint(osam_client):
    """Test for live probe endpoint."""
    response = osam_client.get("/_mgmt/ping")
    assert response.status_code == HTTP_200_OK


@pytest.mark.unit
def test_user_rights_user_exists(mocker, osam_client):
    """Test when the user exists and rights are returned successfully."""
    mock_user_data = {"roles": ["some-role"]}
    mocker.patch(
        "osam.main.app.extra",
        {
            "shutdown_event": threading.Event(),
            "users_sync_trigger": threading.Event(),
            "users_info": {"testuser": mock_user_data},
        },
    )

    mock_build = mocker.patch(
        "osam.main.build_s3_rights",
        return_value={"rights": "mock-rights"},
    )
    mock_update = mocker.patch(
        "osam.main.update_s3_rights_lists",
        return_value={"final": "policy"},
    )

    resp = osam_client.get("/storage/account/testuser/rights")

    assert resp.status_code == HTTP_200_OK
    assert resp.json() == {"final": "policy"}
    mock_build.assert_called_once_with(mock_user_data)
    mock_update.assert_called_once_with({"rights": "mock-rights"})


@pytest.mark.unit
def test_user_rights_user_not_found(mocker, osam_client):
    """Test when the user does not exist (404)."""
    mocker.patch(
        "osam.main.app.extra",
        {"shutdown_event": threading.Event(), "users_sync_trigger": threading.Event(), "users_info": {}},
    )

    resp = osam_client.get("/storage/account/unknown_user/rights")

    assert resp.status_code == HTTP_404_NOT_FOUND
    assert "does not exist" in resp.text


@pytest.mark.unit
def test_user_rights_build_s3_rights_error(mocker, osam_client):
    """Test when build_s3_rights fails (500)."""
    mocker.patch(
        "osam.main.app.extra",
        {
            "shutdown_event": threading.Event(),
            "users_sync_trigger": threading.Event(),
            "users_info": {"testuser": {"roles": ["role"]}},
        },
    )

    mocker.patch(
        "osam.main.build_s3_rights",
        side_effect=RuntimeError("mock failure"),
    )

    resp = osam_client.get("/storage/account/testuser/rights")

    assert resp.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert "mock failure" in resp.text


@pytest.mark.unit
def test_user_rights_update_s3_rights_error(mocker, osam_client):
    """Test when update_s3_rights_lists fails (500)."""
    # empty/no-op shutdown - sync trigger
    mocker.patch(
        "osam.main.app.extra",
        {
            "shutdown_event": threading.Event(),
            "users_sync_trigger": threading.Event(),
            "users_info": {"testuser": {"roles": ["role"]}},
        },
    )

    mocker.patch(
        "osam.main.build_s3_rights",
        return_value={"rights": "data"},
    )
    mocker.patch(
        "osam.main.update_s3_rights_lists",
        side_effect=ValueError("update error"),
    )

    resp = osam_client.get("/storage/account/testuser/rights")

    assert resp.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert "update error" in resp.text


# def test_no_auth_routes():
#     """must be authenticated tests"""
#     # These should return False (no auth needed)
#     assert not must_be_authenticated("/_mgmt/ping")
#     assert not must_be_authenticated("/api")
#     assert not must_be_authenticated("/api.html")
#     assert not must_be_authenticated("/health")

# def test_auth_routes():
#     """must be authenticated tests"""
#     # These should return True (auth needed)
#     assert must_be_authenticated("/some/other/path")
#     assert must_be_authenticated("/api/v1/resource")
#     assert must_be_authenticated("/")
#     assert must_be_authenticated("/_mgmt/pong")
