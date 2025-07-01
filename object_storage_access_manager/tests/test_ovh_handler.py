# Copyright 2025 CS Group
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

"""Unit tests for ovh_handler"""

import os

import pytest
from osam.utils.cloud_provider_api_handler import OVHApiHandler


@pytest.fixture(name="handler")
def handler_fixture(mocker):
    """
    Fixture that initializes OVHApiHandler with a mocked OVH client.
    """
    # Patch environment variables
    mocker.patch.dict(
        os.environ,
        {
            "OVH_ENDPOINT": "ovh-eu",
            "OVH_APPLICATION_KEY": "app-key",
            "OVH_APPLICATION_SECRET": "app-secret",
            "OVH_CONSUMER_KEY": "consumer-key",
        },
    )

    # Patch ovh.Client
    mock_ovh_client = mocker.MagicMock()
    mocker.patch("osam.utils.cloud_provider_api_handler.ovh.Client", return_value=mock_ovh_client)

    # Also patch get("/cloud/project") to simulate service name retrieval
    mock_ovh_client.get.return_value = ["fake-service"]

    return OVHApiHandler()


def test_get_all_users(handler):
    """
    Test get_all_users returns the list of users.
    """

    handler.ovh_client.get.reset_mock()  # clear calls from __init__
    handler.ovh_client.get.return_value = [{"id": "user1"}]

    result = handler.get_all_users()
    assert result == [{"id": "user1"}]
    handler.ovh_client.get.assert_called_once_with(f"/cloud/project/{handler.ovh_service_name}/user")


def test_get_user(handler):
    """
    Test retrieving a specific user by ID.
    """

    handler.ovh_client.get.reset_mock()
    handler.ovh_client.get.return_value = {"id": "user1", "description": "test user"}

    result = handler.get_user("user1")
    assert result["id"] == "user1"
    handler.ovh_client.get.assert_called_once_with(f"/cloud/project/{handler.ovh_service_name}/user/user1")


def test_create_user_status_ok(handler):
    """
    Test creating a user when status immediately becomes 'ok'.
    """

    # Simulate post returning user
    handler.ovh_client.post.return_value = {"id": "user1"}
    # Simulate get returning status 'ok'
    handler.ovh_client.get.return_value = {"status": "ok"}

    result = handler.create_user(description="Test user")
    assert result["id"] == "user1"
    handler.ovh_client.post.assert_any_call(
        f"/cloud/project/{handler.ovh_service_name}/user",
        description="Test user",
        role=None,
        roles=None,
    )
    handler.ovh_client.post.assert_any_call(f"/cloud/project/{handler.ovh_service_name}/user/user1/s3Credentials")


def test_create_user_timeout(handler, mocker):
    """
    Test create_user raises TimeoutError if status never becomes 'ok'.
    """

    handler.ovh_client.post.return_value = {"id": "user1"}
    handler.ovh_client.get.return_value = {"status": "creating"}

    # Patch time.sleep to avoid real delays
    mocker.patch("time.sleep")
    with pytest.raises(TimeoutError):
        handler.create_user(timeout_seconds=1, poll_interval=0.1)


def test_delete_user(handler):
    """
    Test deleting a user.
    """

    handler.ovh_client.delete.return_value = {"result": "success"}

    result = handler.delete_user("user1")
    assert result == {"result": "success"}
    handler.ovh_client.delete.assert_called_once_with(f"/cloud/project/{handler.ovh_service_name}/user/user1")


def test_get_user_s3_access_key_found(handler):
    """
    Test retrieving the S3 access key when present.
    """

    handler.ovh_client.get.reset_mock()
    handler.ovh_client.get.return_value = [{"access": "access-key-123"}]

    result = handler.get_user_s3_access_key("user1")
    assert result == "access-key-123"
    handler.ovh_client.get.assert_called_once_with(
        f"/cloud/project/{handler.ovh_service_name}/user/user1/s3Credentials",
    )


def test_get_user_s3_access_key_missing(handler):
    """
    Test get_user_s3_access_key returns None if credentials list is empty.
    """

    handler.ovh_client.get.return_value = []

    result = handler.get_user_s3_access_key("user1")
    assert result is None


def test_get_user_s3_secret_key(handler):
    """
    Test retrieving the S3 secret key.
    """

    handler.ovh_client.post.return_value = {"secret": "secret-key-abc"}

    result = handler.get_user_s3_secret_key("user1", "access-key-123")
    assert result == "secret-key-abc"
    handler.ovh_client.post.assert_called_once_with(
        f"/cloud/project/{handler.ovh_service_name}/user/user1/s3Credentials/access-key-123/secret",
    )


def test_constructor_with_env_service(mocker):
    """
    Test constructor uses OVH_SERVICE environment variable if set.
    """
    # Patch environment variables
    env = {
        "OVH_ENDPOINT": "ovh-eu",
        "OVH_APPLICATION_KEY": "app-key",
        "OVH_APPLICATION_SECRET": "app-secret",
        "OVH_CONSUMER_KEY": "consumer-key",
        "OVH_SERVICE": "explicit-service",
    }
    mocker.patch.dict(os.environ, env)

    # Patch ovh.Client
    mock_ovh_client = mocker.MagicMock()
    mocker.patch("osam.utils.cloud_provider_api_handler.ovh.Client", return_value=mock_ovh_client)

    handler = OVHApiHandler()

    assert handler.ovh_service_name == "explicit-service"
