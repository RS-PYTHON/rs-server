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

"""Class used to test a Provider."""

import pytest
from rs_server_common.data_retrieval.provider import SearchProductFailed, TimeRange

from .conftest import a_product
from .fake_provider import FakeProvider


class TestAProviderSearch:
    """Class used to test the search functionality of providers."""

    def test_returns_no_product_with_an_empty_timerange(self, start):
        """
        Verifies that no product is returned with an empty time range.

        This test checks if a provider returns an empty dictionary when the search
        is performed with an empty time range.

        Args:
            start (datetime): Start time for testing.

        """
        # TODO parameterize for EodagProvider and FakeProvider
        provider = FakeProvider([a_product("1"), a_product("2")])
        products = provider.search(TimeRange(start, start))
        assert isinstance(products, list)
        assert len(products) == 0

    def test_fails_if_timerange_is_negative(self, start, end):
        """
        Verifies that an exception is raised when the time range is negative.

        This test checks if the provider raises a SearchProductFailed exception when
        the search is performed with a negative time range.

        Args:
            start (datetime): Start time for testing.
            end (datetime): End time for testing.

        """
        # TODO parameterize for EodagProvider and FakeProvider
        provider = FakeProvider([a_product("1"), a_product("2")])
        with pytest.raises(SearchProductFailed) as exc_info:
            provider.search(TimeRange(end, start))  # pylint: disable=arguments-out-of-order
        assert str(exc_info.value) == f"Search timerange is inverted : ({end} -> {start})"
