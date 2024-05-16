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

"""Fake provider."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rs_server_common.data_retrieval.provider import (
    DownloadProductFailed,
    Product,
    Provider,
    SearchProductFailed,
    TimeRange,
)


@dataclass
class DownloadRecord:
    """A download record."""

    product_id: str
    location: Path


class FakeProvider(Provider):
    """Fake implementation of a provider for test purpose."""

    def __init__(self, products: list[Product]):
        """Create a fake provider.

        A fake provider is initialized with the list of products he knows.
        """
        self.products: dict[str, Product] = {product.id_: product for product in products}
        self.last_search: TimeRange | None = None
        self.last_download: DownloadRecord | None = None

    def _specific_search(self, between: TimeRange) -> dict[str, Product]:
        """Search product for fake.

        It records the last search made.
        It fails if the search is in the future.
        It returns all the products otherwise.

        :param between: the search timerange
        :return: all the products
        """
        self.last_search = between
        if between.end > datetime.now():
            raise SearchProductFailed("A FakeProvider failed when searching in the future.")
        return self.products

    def download(self, product_id: str, to_file: Path) -> None:
        """Download for fake the given product.

        The download verifies the product existence.
        If it exists, it creates an empty file at the given location.
        It also records the product id as last downloaded.

        :param product_id: the product to download
        :param to_file: the location where to download.
        :return: None
        """
        self.last_download = DownloadRecord(product_id, to_file)
        if product_id not in self.products:
            raise DownloadProductFailed(f"Product with id '{product_id}' doesn't exist.")
        to_file.touch()
