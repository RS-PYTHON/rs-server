"""Fake provider."""
from datetime import datetime
from pathlib import Path

from rs_server_common.data_retrieval.provider import (
    DownloadProductFailed,
    Product,
    Provider,
    SearchProductFailed,
    TimeRange,
)


class FakeProvider(Provider):
    """Fake implementation of a provider for test purpose."""

    def __init__(self, products: list[Product]):
        """Create a fake provider.

        A fake provider is initialized with the list of products he knows.
        """
        self.products: dict[str, Product] = {product.id_: product for product in products}
        self.last_search: TimeRange | None = None
        self.last_download: str | None = None

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
        self.last_download = product_id
        if product_id not in self.products:
            raise DownloadProductFailed(f"Product with id '{product_id}' doesn't exist.")
        to_file.touch()
