"""Unit test for FakeStorage."""
from pathlib import Path

import pytest
from rs_server_common.data_retrieval.storage import Storage

from tests.data_retrieval.storage.fake_storage import (
    AlreadyLogin,
    AlreadyLogout,
    FakeStorage,
    NotLogged,
    StorageRecord,
)


@pytest.fixture
def _file(tmp_path) -> Path:
    file = tmp_path / "a_file.txt"
    file.touch()
    return file


@pytest.fixture
def _not_found_file(tmp_path) -> Path:
    return tmp_path / "not_found.txt"


@pytest.fixture
def _location(tmp_path) -> Path:
    return tmp_path / "uploaded"


class TestAFakeStorage:
    """Class used to test the functionality of the FakeStorage class."""

    def test_is_a_storage(self):
        """
        Verifies that FakeStorage is an instance of the Storage class.

        This test checks if an instance of FakeStorage is also an instance of the Storage class.

        """
        storage = FakeStorage()
        assert isinstance(storage, Storage)

    def test_is_initially_not_logged(self):
        """
        Verifies that FakeStorage is initially not logged.

        This test checks if a newly created FakeStorage instance is not logged by default.

        """
        storage = FakeStorage()
        assert not storage.logged

    def test_is_logged_after_login(self):
        """
        Verifies that FakeStorage is logged after the login operation.

        This test checks if a FakeStorage instance is logged after the login operation.

        """
        storage = FakeStorage()
        storage.login()
        assert storage.logged

    def test_cant_login_if_logged(self):
        """
        Verifies that FakeStorage raises AlreadyLogin exception when trying to login while already logged.

        This test checks if FakeStorage raises an AlreadyLogin exception when attempting to login
        while already logged in.

        """
        storage = FakeStorage()
        storage.login()
        with pytest.raises(AlreadyLogin) as exc_info:
            storage.login()
        assert str(exc_info.value) == "Already login."

    def test_isnt_logged_after_logout(self):
        """
        Verifies that FakeStorage is not logged after the logout operation.

        This test checks if a FakeStorage instance is not logged after the logout operation.

        """
        storage = FakeStorage()
        storage.login()
        storage.logout()
        assert not storage.logged

    def test_cant_logout_is_not_logged(self):
        """
        Verifies that FakeStorage raises AlreadyLogout exception when trying to logout while not logged.

        This test checks if FakeStorage raises an AlreadyLogout exception when attempting to logout
        while not logged in.

        """
        storage = FakeStorage()
        with pytest.raises(AlreadyLogout) as exc_info:
            storage.logout()
        assert str(exc_info.value) == "Already logout."

    def test_cant_store_if_not_logged(self, _file, _location):
        """
        Verifies that FakeStorage raises NotLogged exception when trying to store while not logged.

        This test checks if FakeStorage raises a NotLogged exception when attempting to store a file
        while not logged in.

        """
        storage = FakeStorage()
        with pytest.raises(NotLogged) as exc_info:
            storage.store(_file, _location)
        assert str(exc_info.value) == "Not logged."

    def test_store_fails_if_file_doesnt_exists(self, _not_found_file, _location):
        """
        Verifies that FakeStorage raises FileNotFoundError when trying to store a non-existent file.

        This test checks if FakeStorage raises a FileNotFoundError when attempting to store a file
        that doesn't exist.

        """
        storage = FakeStorage()
        storage.login()
        with pytest.raises(FileNotFoundError):
            storage.store(_not_found_file, _location)

    def test_records_the_last_store_made(self, _file, _location):
        """
        Verifies that FakeStorage records the last store operation made.

        This test checks if FakeStorage records the last store operation made, and if the recorded
        information matches the expected StorageRecord.

        """
        storage = FakeStorage()
        storage.login()

        assert storage.last_upload is None

        storage.store(_file, _location)

        assert storage.last_upload == StorageRecord(_file, _location)
