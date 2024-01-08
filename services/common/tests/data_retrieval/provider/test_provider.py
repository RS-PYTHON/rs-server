import pytest
from rs_server_common.data_retrieval.provider import SearchProductFailed, TimeRange

from tests.data_retrieval.provider.conftest import a_product
from tests.data_retrieval.provider.fake_provider import FakeProvider


class TestAProviderSearch:
    def test_returns_no_product_with_an_empty_timerange(self, start):
        # TODO parameterize for EodagProvider and FakeProvider
        provider = FakeProvider([a_product("1"), a_product("2")])
        products = provider.search(TimeRange(start, start))
        assert isinstance(products, dict)
        assert len(products) == 0

    def test_fails_if_timerange_is_negative(self, start, end):
        # TODO parameterize for EodagProvider and FakeProvider
        provider = FakeProvider([a_product("1"), a_product("2")])

        with pytest.raises(SearchProductFailed) as exc_info:
            provider.search(TimeRange(end, start))
        assert str(exc_info.value) == f"Search timerange is inverted : ({end} -> {start})"
