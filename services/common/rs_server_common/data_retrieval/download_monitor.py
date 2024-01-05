"""Download monitoring."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DownloadStatus(Enum):
    """Status of a product download."""

    NOT_STARTED = 1
    IN_PROGRESS = 2
    FAILED = 3
    DONE = 4


@dataclass
class ProductDownload:
    """A product download."""

    id_: str
    status: DownloadStatus
    start: datetime | None
    end: datetime | None
    error: str = ""


class DownloadMonitor(ABC):
    """A monitor for product downloads.

    It keeps track of the ongoing and failed downloads.
    """

    @abstractmethod
    def requested(self, product_id: str) -> None:
        """A download has been requested.

        :param product_id: id of the product to download
        :return: None
        """

    @abstractmethod
    def started(self, product_id: str, at_time: datetime) -> None:
        """A download has been started.

        :param product_id: id of the product to download
        :param at_time: start time of the download
        :return: None
        """

    @abstractmethod
    def completed(self, product_id: str, at_time: datetime) -> None:
        """A download has been completed.

        :param product_id: id of the downloaded product
        :param at_time: end time of the download
        :return: None
        """

    @abstractmethod
    def failed(self, product_id: str, at_time: datetime, with_error: str) -> None:
        """A download has failed.

        :param product_id: id of the downloaded product
        :param at_time: end time of the download
        :param with_error: message of the error
        :return: None
        """
