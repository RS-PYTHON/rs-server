"""Storage module."""
from abc import ABC, abstractmethod
from pathlib import Path


class Storage(ABC):
    """A storage."""

    @abstractmethod
    def login(self) -> None:
        """Log in to the storage.

        :return: None
        """

    @abstractmethod
    def logout(self) -> None:
        """Log out to the storage.

        :return: None
        """

    @abstractmethod
    def store(self, file: Path, location: Path) -> None:
        """Upload the local file to the given location in the storage.

        :param file: local file to upload
        :param location: relative location of the upload file in the storage
        :return: None
        """
