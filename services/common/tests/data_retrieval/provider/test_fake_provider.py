"""Unit tests for fake provider."""
from datetime import timedelta

import pytest
from rs_server_common.data_retrieval.provider import (
    DownloadProductFailed,
    Provider,
    SearchProductFailed,
    TimeRange,
)

from tests.data_retrieval.provider.conftest import a_product
from tests.data_retrieval.provider.fake_provider import DownloadRecord, FakeProvider


class TestAFakeProvider:
    def test_is_a_provider(self):
        provider = FakeProvider([])
        assert isinstance(provider, Provider)

    def test_is_initialized_with_the_list_of_available_products(self):
        provider = FakeProvider([a_product("1"), a_product("2")])

        assert isinstance(provider.products, dict)
        assert set(provider.products) == {"2", "1"}
        assert provider.products["1"] == a_product("1")
        assert provider.products["2"] == a_product("2")

    def test_cant_search_in_the_future(self, start, in_the_future):
        provider = FakeProvider([a_product("1"), a_product("2")])

        with pytest.raises(SearchProductFailed) as exc_info:
            provider.search(TimeRange(start, in_the_future))

        assert str(exc_info.value) == "A FakeProvider failed when searching in the future."

    def test_returns_all_products_when_searching_in_the_past(self, start, end):
        provider = FakeProvider([a_product("1"), a_product("2")])
        products = provider.search(TimeRange(start, end))

        assert products == provider.products

    def test_records_the_timerange_used_for_the_last_search(self, start, end):
        provider = FakeProvider([a_product("1"), a_product("2")])

        assert provider.last_search is None

        provider.search(TimeRange(start, end))
        assert provider.last_search == TimeRange(start, end)

        provider.search(TimeRange(start, end + timedelta(days=1)))
        assert provider.last_search == TimeRange(start, end + timedelta(days=1))

    def test_cant_download_an_unknown_file(self, tmp_path):
        provider = FakeProvider([a_product("1"), a_product("2")])

        with pytest.raises(DownloadProductFailed) as exc_info:
            provider.download("3", tmp_path / "downloaded.txt")

        assert str(exc_info.value) == "Product with id '3' doesn't exist."

    def test_creates_an_empty_file_at_the_given_path(self, tmp_path):
        provider = FakeProvider([a_product("1"), a_product("2")])
        downloaded_file = tmp_path / "downloaded.txt"

        provider.download("1", downloaded_file)

        assert downloaded_file.exists()
        assert downloaded_file.is_file()

    def test_record_the_last_download_made(self, tmp_path):
        provider = FakeProvider([a_product("1"), a_product("2")])
        downloaded_file = tmp_path / "downloaded.txt"

        assert provider.last_download is None

        provider.download("1", downloaded_file)
        assert isinstance(provider.last_download, DownloadRecord)
        assert provider.last_download.product_id == "1"
        assert provider.last_download.location == downloaded_file

        provider.download("2", downloaded_file)
        assert isinstance(provider.last_download, DownloadRecord)
        assert provider.last_download.product_id == "2"
        assert provider.last_download.location == downloaded_file
