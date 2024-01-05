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
def a_file(tmp_path) -> Path:
    return tmp_path / "a_file.txt"


@pytest.fixture
def a_location(tmp_path) -> Path:
    return tmp_path / "uploaded"


class TestAFakeStorage:
    def test_is_a_storage(self):
        storage = FakeStorage()
        assert isinstance(storage, Storage)

    def test_is_initially_not_logged(self):
        storage = FakeStorage()
        assert not storage.logged

    def test_is_logged_after_login(self):
        storage = FakeStorage()
        storage.login()
        assert storage.logged

    def test_cant_login_if_logged(self):
        storage = FakeStorage()
        storage.login()
        with pytest.raises(AlreadyLogin) as exc_info:
            storage.login()
        assert str(exc_info.value) == "Already login."

    def test_isnt_logged_after_logout(self):
        storage = FakeStorage()
        storage.login()
        storage.logout()
        assert not storage.logged

    def test_cant_logout_is_not_logged(self):
        storage = FakeStorage()
        with pytest.raises(AlreadyLogout) as exc_info:
            storage.logout()
        assert str(exc_info.value) == "Already logout."

    def test_cant_store_if_not_logged(self, a_file, a_location):
        storage = FakeStorage()
        with pytest.raises(NotLogged) as exc_info:
            storage.store(a_file, a_location)
        assert str(exc_info.value) == "Not logged."

    def test_records_the_last_store_made(self, a_file, a_location):
        storage = FakeStorage()
        storage.login()

        assert storage.last_upload is None

        storage.store(a_file, a_location)

        assert storage.last_upload == StorageRecord(a_file, a_location)
