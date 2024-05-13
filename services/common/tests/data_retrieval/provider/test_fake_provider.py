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

"""Unit tests for fake provider."""

from datetime import timedelta

import pytest
from rs_server_common.data_retrieval.provider import (
    DownloadProductFailed,
    Provider,
    SearchProductFailed,
    TimeRange,
)

from .conftest import a_product
from .fake_provider import FakeProvider


class TestAFakeProvider:
    """Class used to test the functionality of the FakeProvider class."""

    def test_is_a_provider(self):
        """
        Verifies that FakeProvider is an instance of the Provider class.

        This test checks if an instance of FakeProvider is also an instance of the Provider class.

        """
        provider = FakeProvider([])
        assert isinstance(provider, Provider)

    def test_is_initialized_with_the_list_of_available_products(self):
        """
        Verifies that FakeProvider is initialized with the given list of available products.

        This test checks if an instance of FakeProvider is properly initialized with the provided list
        of available products, and if the products are correctly stored in the internal dictionary.

        """
        provider = FakeProvider([a_product("1"), a_product("2")])

        assert isinstance(provider.products, dict)
        assert set(provider.products) == {"2", "1"}
        assert provider.products["1"] == a_product("1")
        assert provider.products["2"] == a_product("2")

    def test_cant_search_in_the_future(self, start, in_the_future):
        """
        Verifies that FakeProvider raises SearchProductFailed when searching in the future.

        This test checks if FakeProvider raises a SearchProductFailed exception when attempting to
        search for products in the future.

        """
        provider = FakeProvider([a_product("1"), a_product("2")])

        with pytest.raises(SearchProductFailed) as exc_info:
            provider.search(TimeRange(start, in_the_future))

        assert str(exc_info.value) == "A FakeProvider failed when searching in the future."

    def test_returns_all_products_when_searching_in_the_past(self, start, end):
        """
        Verifies that FakeProvider returns all products when searching in the past.

        This test checks if FakeProvider returns all available products when searching within a time range
        in the past.

        """
        provider = FakeProvider([a_product("1"), a_product("2")])
        products = provider.search(TimeRange(start, end))

        assert products == provider.products

    def test_records_the_timerange_used_for_the_last_search(self, start, end):
        """
        Verifies that FakeProvider records the time range used for the last search.

        This test checks if FakeProvider records the time range used for the last search operation.

        """
        provider = FakeProvider([a_product("1"), a_product("2")])

        assert provider.last_search is None

        provider.search(TimeRange(start, end))
        assert provider.last_search == TimeRange(start, end)

        provider.search(TimeRange(start, end + timedelta(days=1)))
        assert provider.last_search == TimeRange(start, end + timedelta(days=1))

    def test_cant_download_an_unknown_file(self, tmp_path):
        """
        Verifies that FakeProvider raises DownloadProductFailed for downloading an unknown file.

        This test checks if FakeProvider raises a DownloadProductFailed exception when attempting to
        download an unknown file.

        """
        provider = FakeProvider([a_product("1"), a_product("2")])

        with pytest.raises(DownloadProductFailed) as exc_info:
            provider.download("3", tmp_path / "downloaded.txt")

        assert str(exc_info.value) == "Product with id '3' doesn't exist."

    def test_creates_an_empty_file_at_the_given_path(self, tmp_path):
        """
        Verifies that FakeProvider creates an empty file at the given path.

        This test checks if FakeProvider can successfully download a file, creating an empty file at
        the specified location.

        """
        provider = FakeProvider([a_product("1"), a_product("2")])
        downloaded_file = tmp_path / "downloaded.txt"

        provider.download("1", downloaded_file)

        assert downloaded_file.exists()
        assert downloaded_file.is_file()

    def test_record_the_last_download_made(self, tmp_path):
        """
        Verifies that FakeProvider records the last download made.

        This test checks if FakeProvider records the last download made, and if the recorded information
        matches the expected DownloadRecord.

        """
        provider = FakeProvider([a_product("1"), a_product("2")])
        downloaded_file = tmp_path / "downloaded.txt"

        assert provider.last_download is None

        provider.download("1", downloaded_file)
        if provider.last_download:
            assert provider.last_download.product_id == "1"
            assert provider.last_download.location == downloaded_file

            provider.download("2", downloaded_file)
            assert provider.last_download.product_id == "2"
            assert provider.last_download.location == downloaded_file
