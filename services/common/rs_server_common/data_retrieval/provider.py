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

    def __bool__(self) -> bool:
        return self.start is not None and self.end is not None


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
        if between:
            if between.duration() == timedelta(0):
                return []
            if between.duration() < timedelta(0):
                raise SearchProductFailed(f"Search timerange is inverted : ({between.start} -> {between.end})")
        return self._specific_search(between, **kwargs)

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
