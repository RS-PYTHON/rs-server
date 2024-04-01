"""Provider mechanism."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass
class TimeRange:
    """A time range."""

    start: datetime
    end: datetime

    def duration(self) -> timedelta:
        """Duration of the timerange.

        Returns: duration of the timerange
        """
        return self.end - self.start


@dataclass
class Product:
    """A product.

    A product has an external identifier and a dictionary of metadata.
    """

    id_: str
    metadata: dict[str, str]


class CreateProviderFailed(Exception):
    """Exception raised when an error occurred during the init of a provider."""


class SearchProductFailed(Exception):
    """Exception raised when an error occurred during the search."""


class DownloadProductFailed(Exception):
    """Exception raised when an error occurred during the download."""


class Provider(ABC):
    """A product provider.

    A provider gives a common interface to search for files from an external data source
    and download them locally.
    """

    def search(self, between: TimeRange, **kwargs) -> Any:
        """Search for products with the given time range.

        The search result is a dictionary of products found indexed by id.

        Args:
            between: the search period

        Returns:
            The files found indexed by file id. Specific to each provider.

        """
        if between.duration() == timedelta(0):
            return []
        if between.duration() < timedelta(0):
            raise SearchProductFailed(f"Search timerange is inverted : ({between.start} -> {between.end})")
        return self._specific_search(between, **kwargs)

    def session_search(self, sessionId: str, platform: str, start_date: datetime, stop_date: datetime, **kwargs):
        # some checks to be implemented here
        # Transform sessionID and platform to SessionIds / SessionID or platforms / platform
        if sessionId:
            if isinstance(sessionId, list):
                mapped_search_args = dict(SessionIds=", ".join(sessionId))
            elif isinstance(sessionId, str):
                mapped_search_args = dict(SessionId=sessionId)
        if platform:
            if isinstance(platform, list):
                mapped_search_args = dict(platforms=", ".join(platform))
            elif isinstance(platform, str):
                mapped_search_args = dict(platform=platform)
        return self._specific_session_search(mapped_search_args)

    @abstractmethod
    def _specific_search(self, between: TimeRange) -> Any:
        """Search for products with the given time range.

        Specific search for products after common verification.

        Args:
            between: the search period

        Returns:
            the files found indexed by file id.

        """

    @abstractmethod
    def download(self, product_id: str, to_file: Path) -> None:
        """Download the given product to the given local path.

        Args:
            product_id: id of the product to download
            to_file: path where the file should be downloaded

        Returns:
            None

        """
