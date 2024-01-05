"""Fake storage for test purpose."""
from dataclasses import dataclass
from pathlib import Path

from rs_server_common.data_retrieval.storage import Storage


class AlreadyLogin(Exception):
    """Exception raised when login twice."""

    def __init__(self):
        """Create an AlreadyLogin exception."""
        super().__init__("Already login.")


class AlreadyLogout(Exception):
    """Exception raised when logout twice."""

    def __init__(self):
        """Create an AlreadyLogout exception."""
        super().__init__("Already logout.")


class NotLogged(Exception):
    """Exception raised when using the storage while not logged."""

    def __init__(self):
        """Create a NotLogged exception."""
        super().__init__("Not logged.")


@dataclass
class StorageRecord:
    """A storage record."""

    uploaded_file: Path
    location: Path


class FakeStorage(Storage):
    """A fake Storage."""

    def __init__(self):
        """Create a fake storage."""
        self.logged: bool = False
        self.last_upload: StorageRecord | None = None

    def login(self) -> None:
        """Login to the storage.

        The login fails if already logged.
        """
        if self.logged:
            raise AlreadyLogin()
        self.logged = True

    def logout(self) -> None:
        """Logout to the storage.

        The logout fails if already not logged.
        """
        if not self.logged:
            raise AlreadyLogout()
        self.logged = False

    def store(self, file: Path, location: Path) -> None:
        """Records the last store made.


        :param file: local file to upload
        :param location: relative location of the upload file in the storage
        :return: None
        """
        if not self.logged:
            raise NotLogged()
        self.last_upload = StorageRecord(file, location)
