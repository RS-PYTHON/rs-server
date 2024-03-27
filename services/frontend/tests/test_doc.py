"""Tests for the docs endpoints."""

import json
from json import JSONDecodeError

import pytest
from rs_server_frontend.main import Frontend, FrontendFailed
from starlette.status import HTTP_200_OK

# pylint: disable=missing-function-docstring,too-few-public-methods


class TestStartingApplication:
    """Verifies the openapi loading at the start of the frontend application."""

    def test_fails_if_the_openapi_spec_is_not_found(self, monkeypatch):
        monkeypatch.setenv("RSPY_OPENAPI_FILE", "file/not/found")
        with pytest.raises(FrontendFailed) as exc_info:
            Frontend()
        assert str(exc_info.value) == "Unable to serve openapi specification."
        cause = exc_info.value.__cause__
        assert isinstance(cause, IOError)
        assert isinstance(cause.__cause__, FileNotFoundError)

    def test_fails_if_the_openapi_spec_is_not_relevant(
        self,
        monkeypatch,
        invalid_openapi_spec_file,
    ):
        monkeypatch.setenv("RSPY_OPENAPI_FILE", str(invalid_openapi_spec_file))
        with pytest.raises(FrontendFailed) as exc_info:
            Frontend()
        assert str(exc_info.value) == "Unable to serve openapi specification."
        cause = exc_info.value.__cause__
        assert isinstance(cause, ValueError)
        assert isinstance(cause.__cause__, JSONDecodeError)


class TestGettingTheOpenapiSpecification:
    """Verifies the openapi returns when getting the specification."""

    def test_returns_the_configured_openapi_file_content(
        self,
        client,
        expected_openapi_spec,
    ):
        response = client.get("/openapi.json")
        assert response.status_code == HTTP_200_OK
        json_body = json.loads(response.content)
        assert json_body == expected_openapi_spec
