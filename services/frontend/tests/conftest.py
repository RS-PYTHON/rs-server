""""Common fixtures."""

import json
from pathlib import Path

import pytest
from rs_server_frontend.main import Frontend
from starlette.testclient import TestClient


@pytest.fixture(scope="session")
def resources_test_path() -> Path:
    """The root path for test resources."""
    return Path(__file__).parent / "resources"


@pytest.fixture(scope="session")
def openapi_spec_file(resources_test_path) -> Path:
    """The path to the nominal openapi."""
    return resources_test_path / "openapi.json"


@pytest.fixture(scope="session")
def invalid_openapi_spec_file(resources_test_path) -> Path:
    """The path to the invalid openapi."""
    return resources_test_path / "wrong-openapi.json"


@pytest.fixture(scope="session")
def expected_openapi_spec(openapi_spec_file) -> dict:
    """The nominal openapi."""
    with open(openapi_spec_file, "r") as file:
        return json.load(file)


@pytest.fixture
def client(monkeypatch, openapi_spec_file) -> TestClient:
    """The nominal application client for test purpose."""
    monkeypatch.setenv("RSPY_OPENAPI_FILE", str(openapi_spec_file))
    app = Frontend().app
    with TestClient(app) as the_client:
        yield the_client
