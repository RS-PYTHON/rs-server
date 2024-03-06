import pytest


class TestStartingApplication:
    @pytest.mark.xfail
    def test_fails_if_the_openapi_spec_is_not_found(self):
        assert False

    @pytest.mark.xfail
    def test_fails_if_the_openapi_spec_is_not_relevant(self):
        assert False


class TestGettingTheOpenapiSpecification:
    @pytest.mark.xfail
    def test_returns_the_configured_openapi_file_content(self):
        assert False
