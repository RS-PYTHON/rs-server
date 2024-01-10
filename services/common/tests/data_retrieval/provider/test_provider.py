"""Class used to test a Provider."""
import pytest

from services.common.rs_server_common.data_retrieval.provider import (
    SearchProductFailed,
    TimeRange,
)

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
        assert isinstance(products, dict)
        assert len(products) == 0

    def test_fails_if_timerange_is_negative(self, _start, _end):
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
            provider.search(TimeRange(_end, _start))
        assert str(exc_info.value) == f"Search timerange is inverted: ({_end} -> {_start})"
