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

""""Common fixtures."""

import json
from pathlib import Path
from typing import Generator

import pytest
from rs_server_frontend.main import Frontend
from starlette.testclient import TestClient


@pytest.fixture(scope="session")
def resources_test_path() -> Path:
    """The root path for test resources."""
    return Path(__file__).parent / "resources"


@pytest.fixture(scope="session")
def openapi_spec_file(resources_test_path) -> Path:  # pylint: disable=redefined-outer-name
    """The path to the nominal openapi."""
    return resources_test_path / "openapi.json"


@pytest.fixture(scope="session")
def invalid_openapi_spec_file(resources_test_path) -> Path:  # pylint: disable=redefined-outer-name
    """The path to the invalid openapi."""
    return resources_test_path / "wrong-openapi.json"


@pytest.fixture(scope="session")
def expected_openapi_spec(openapi_spec_file) -> dict:  # pylint: disable=redefined-outer-name
    """The nominal openapi."""
    with open(openapi_spec_file, "r", encoding="utf-8") as file:
        return json.load(file)


@pytest.fixture
def client(monkeypatch, openapi_spec_file) -> Generator[TestClient, None, None]:  # pylint: disable=redefined-outer-name
    """The nominal application client for test purpose."""
    monkeypatch.setenv("RSPY_OPENAPI_FILE", str(openapi_spec_file))
    app = Frontend().app
    with TestClient(app) as the_client:
        yield the_client
