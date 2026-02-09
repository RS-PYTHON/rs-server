# Copyright 2023-2025 Airbus, CS Group
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

import pytest
from rs_server_common import settings as common_settings
from rs_server_common.utils.pytest import pytest_common_tests
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
def test_get_user_rights_user_exists(mocker):
    """Test when the user exists and rights are returned successfully."""
    os.environ["RSPY_LOCAL_MODE"] = "1"
    reload(common_settings)
    mocker.patch("rs_server_common.middlewares.apply_middlewares", lambda app: app)

    from osam.main import (  # pylint: disable = import-outside-toplevel
        __get_user_rights,
    )

    user = "testuser"
    mock_user_data = {"roles": ["some-role"]}
    mocker.patch(
        "osam.main.app.extra",
        {
            "shutdown_event": threading.Event(),
            "users_sync_trigger": threading.Event(),
            "users_info": {user: mock_user_data},
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

    assert __get_user_rights(user) == {"final": "policy"}
    mock_build.assert_called_once_with(mock_user_data)
    mock_update.assert_called_once_with({"rights": "mock-rights"})


@pytest.mark.unit
def test_get_user_rights_user_not_found(mocker):
    """Test when the user does not exist (404)."""
    os.environ["RSPY_LOCAL_MODE"] = "1"
    reload(common_settings)
    mocker.patch("rs_server_common.middlewares.apply_middlewares", lambda app: app)

    from osam.main import (  # pylint: disable = import-outside-toplevel
        __get_user_rights,
    )

    mocker.patch(
        "osam.main.app.extra",
        {"shutdown_event": threading.Event(), "users_sync_trigger": threading.Event(), "users_info": {}},
    )
    assert not __get_user_rights("unknown_user")


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

    mock_update = mocker.patch(
        "osam.main.__get_user_rights",
        return_value={"final": "policy"},
    )

    resp = osam_client.get("/storage/account/testuser/rights")

    assert resp.status_code == HTTP_200_OK
    assert resp.json() == {"final": "policy"}

    mock_update.assert_called_once_with("testuser")


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


@pytest.mark.unit
def test_apply_user_obs_access_policy_user_exists(mocker, osam_client):
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

    mocker.patch(
        "osam.main.__get_user_rights",
        return_value={"final": "policy"},
    )

    mocker.patch(
        "osam.main.apply_user_access_policy",
        return_value=(True, {"detail": "Policy applied"}),
    )

    resp = osam_client.post("/storage/account/testuser/update")

    assert resp.status_code == HTTP_200_OK
    assert resp.json() == {"detail": "Policy applied"}


@pytest.mark.unit
def test_apply_user_obs_access_policy_user_not_found(mocker, osam_client):
    """Test when the user does not exist (404)."""
    mocker.patch(
        "osam.main.app.extra",
        {"shutdown_event": threading.Event(), "users_sync_trigger": threading.Event(), "users_info": {}},
    )

    resp = osam_client.post("/storage/account/unknown_user/update")

    assert resp.status_code == HTTP_404_NOT_FOUND
    assert "does not exist" in resp.text


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


def test_handle_exceptions_middleware(osam_client, mocker):
    """Test that HandleExceptionsMiddleware handles and logs errors as expected."""
    pytest_common_tests.test_handle_exceptions_middleware(osam_client, mocker)
