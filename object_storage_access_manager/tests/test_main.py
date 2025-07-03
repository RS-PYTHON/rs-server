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
import os
import threading
from importlib import reload
from unittest.mock import AsyncMock

import pytest
from rs_server_common import settings as common_settings
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


def test_get_credentials_success(mocker, osam_client):
    """
    Test the /storage/account/credentials endpoint returns user credentials successfully.

    This test mocks:
      - `oauth2.get_user_info` async call to return a user object with `user_login`.
      - `get_user_s3_credentials` to return mocked credentials.

    It verifies the endpoint responds with HTTP 200 and returns the expected credentials JSON.
    """
    # Mock async oauth2.get_user_info to return an object with user_login attribute
    mock_user_info = AsyncMock()
    mock_user_info.user_login = "testuser"
    mocker.patch("osam.main.oauth2.get_user_info", return_value=mock_user_info)

    # Mock get_user_s3_credentials to return some dummy credentials
    expected_creds = {"access_key": "AKIA...", "secret_key": "SECRET"}
    mocker.patch("osam.main.get_user_s3_credentials", return_value=expected_creds)

    response = osam_client.get("/storage/account/credentials")
    assert response.status_code == 200
    assert response.json() == expected_creds


def test_get_credentials_unauthenticated(mocker, osam_client):
    """
    Test the /storage/account/credentials endpoint handles unauthenticated access properly.

    This test mocks `oauth2.get_user_info` to raise an Exception simulating unauthorized access.

    It verifies the endpoint returns a non-200 HTTP status (e.g. 401, 403, 500) and error message.
    """

    # Mock async oauth2.get_user_info to raise an exception (unauthenticated)
    async def raise_unauthorized(*args, **kwargs):
        raise Exception("Unauthorized")  # pylint: disable = broad-exception-raised

    mocker.patch("osam.main.oauth2.get_user_info", side_effect=raise_unauthorized)

    response = osam_client.get("/storage/account/credentials")
    assert response.status_code != 200
    assert "Unauthorized" in response.text or response.status_code in (401, 403, 500)


def test_accounts_update_triggers_sync(mocker, osam_client):
    """
    Test POST /storage/accounts/update triggers the background sync task.

    This test mocks the `set` method of the `users_sync_trigger` threading.Event
    inside `app.extra` to verify it is called.
    """
    from osam.main import app  # pylint: disable = import-outside-toplevel

    mock_event = mocker.Mock()
    app.extra["users_sync_trigger"] = mock_event

    response = osam_client.post("/storage/accounts/update")

    assert response.status_code == 200
    assert "algorithm for updating" in response.text
    mock_event.set.assert_called_once()


def test_main_osam_task_with_shutdown_event_true(mocker):
    """
    Verify that main_osam_task exits immediately without performing any synchronization
    when the shutdown event is already set before entering the loop.

    This ensures that:
    - link_rspython_users_and_obs_users is not called.
    - build_users_data_map is not called.
    """
    os.environ["RSPY_LOCAL_MODE"] = "1"
    reload(common_settings)
    mocker.patch("rs_server_common.middlewares.apply_middlewares", lambda app: app)

    from osam.main import (  # pylint: disable = import-outside-toplevel
        app,
        main_osam_task,
    )

    mock_event_sync = mocker.Mock()
    mock_event_sync.wait.return_value = True
    shutdown_event = mocker.Mock()
    shutdown_event.is_set.return_value = True
    app.extra = {
        "users_sync_trigger": mock_event_sync,
        "shutdown_event": shutdown_event,
        "users_info": {},
    }

    mock_link = mocker.patch("osam.main.link_rspython_users_and_obs_users")
    mock_build = mocker.patch("osam.main.build_users_data_map")
    main_osam_task(timeout=0)
    mock_link.assert_not_called()
    mock_build.assert_not_called()


def test_main_osam_task_runs_once_and_exits(mocker):
    """
    Verify that main_osam_task performs exactly one iteration of synchronization
    and exits cleanly after the shutdown event becomes set.

    This ensures that:
    - link_rspython_users_and_obs_users is called once.
    - build_users_data_map is called once.
    - The loop exits after the second shutdown_event.is_set() returns True.
    """
    # Patch app.extra and the functions it relies on
    os.environ["RSPY_LOCAL_MODE"] = "1"
    reload(common_settings)
    from osam.main import (  # pylint: disable = import-outside-toplevel
        app,
        main_osam_task,
    )

    mock_event_sync = mocker.Mock()
    mock_event_sync.wait.return_value = True
    shutdown_event = mocker.Mock()
    shutdown_event.is_set.side_effect = [False, True]  # first call False, second call True (exit loop)

    app.extra = {
        "users_sync_trigger": mock_event_sync,
        "shutdown_event": shutdown_event,
        "users_info": {},
    }

    mock_link = mocker.patch("osam.main.link_rspython_users_and_obs_users")
    mock_build = mocker.patch("osam.main.build_users_data_map")
    main_osam_task(timeout=0)

    mock_link.assert_called_once()
    mock_build.assert_called_once()


def test_main_osam_task_runs_with_exception(mocker):
    """
    Verify that main_osam_task correctly logs an exception when link_rspython_users_and_obs_users
    raises an error during synchronization, and then exits cleanly.

    This ensures that:
    - logger.exception is called with the expected message.
    - The loop continues and exits on shutdown_event.
    """

    os.environ["RSPY_LOCAL_MODE"] = "1"
    reload(common_settings)
    mocker.patch("rs_server_common.middlewares.apply_middlewares", lambda app: app)

    from osam.main import (  # pylint: disable = import-outside-toplevel
        app,
        main_osam_task,
    )

    mock_event_sync = mocker.Mock()
    mock_event_sync.wait.return_value = True
    shutdown_event = mocker.Mock()
    shutdown_event.is_set.side_effect = [False, True]
    app.extra = {
        "users_sync_trigger": mock_event_sync,
        "shutdown_event": shutdown_event,
        "users_info": {},
    }
    mock_link = mocker.patch("osam.main.link_rspython_users_and_obs_users")
    mock_link.side_effect = Exception
    mock_logger_exception = mocker.patch("osam.main.logger.exception")
    main_osam_task(timeout=0)
    mock_logger_exception.assert_any_call("Handle cancellation: ")
