# Copyright 2023-2025 Airbus, CS Group
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

"""Module used to configure pytests."""

# Ignore not-at-top level import errors

# pylint: disable=C0413, ungrouped-imports, unused-argument
# flake8: noqa: F402

import pytest
import requests


# Mock Response Class
class MockResponse:
    """
    Lightweight mock implementation of a requests.Response object.
    This class simulates the minimal behavior needed for tests that validate
    functions interacting with http responses.
    """

    def __init__(self, json_data, status_code=200, raise_error=False):
        """
        Initializes a mock http response.

        Args:
            json_data (Any): The value returned by the json() method.
            status_code (int, optional): http status code to simulate.
                Defaults to 200.
            raise_error (bool, optional): Forces raise_for_status() to
                raise a requests.HTTPError regardless of status_code.
                Defaults to False.
        """
        self._json_data = json_data
        self.status_code = status_code
        self.raise_error = raise_error

    def json(self):
        """
        Returns the preconfigured JSON payload.
        """
        return self._json_data

    def raise_for_status(self):
        """
        Simulates requests.Response.raise_for_status().

        Behavior:
            - Raises requests.HTTPError if:
                - raise_error is True OR
                - status_code is >= 400

        Raises:
            requests.HTTPError: When an http error condition is simulated.
        """
        if self.raise_error or self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def _mock_os_env(monkeypatch):
    monkeypatch.setenv("RSPY_HOST_OSAM", "https://dummy-osam")
    return "https://dummy-osam"


@pytest.fixture
def _mock_get_success(monkeypatch):
    """Mock requests.get for successful CSV fetch."""

    def _mock_get(url, timeout):
        return MockResponse(
            json_data=[
                ["*", "*", "*", "30", "rspython-ops-catalog-all-production"],
                ["copernicus", "s1-l1", "*", "10", "rspython-ops-catalog-copernicus-s1-l1"],
                ["copernicus", "s1-aux", "*", "40", "rspython-ops-catalog-copernicus-s1-aux"],
                ["copernicus", "s1-aux", "orbsct", "7300", "rspython-ops-catalog-copernicus-s1-aux-infinite"],
            ],
            status_code=200,
        )

    monkeypatch.setattr(requests, "get", _mock_get)
    return _mock_get


@pytest.fixture
def _mock_get_network_error(monkeypatch):
    """Mock requests.get to simulate a network failure."""

    def _mock_get(url, timeout):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(requests, "get", _mock_get)
    return _mock_get


@pytest.fixture
def _mock_get_invalid_json(monkeypatch):
    """Mock requests.get returning non-list JSON."""

    def _mock_get(url, timeout):
        return MockResponse(json_data={"not": "a list"})

    monkeypatch.setattr(requests, "get", _mock_get)
    return _mock_get


@pytest.fixture
def _mock_get_row_not_list(monkeypatch):
    """Mock returning a list where elements are NOT lists."""

    def _mock_get(url, timeout):
        return MockResponse(json_data=["a", "b", "c"])  # invalid

    monkeypatch.setattr(requests, "get", _mock_get)
    return _mock_get


@pytest.fixture
def _mock_get_non_string(monkeypatch):
    """Mock returning a list containing non-string elements inside a row."""

    def _mock_get(url, timeout):
        return MockResponse(json_data=[["a", 123, "b"]])  # 123 invalid

    monkeypatch.setattr(requests, "get", _mock_get)
    return _mock_get


@pytest.fixture
def _mock_get_row_wrong_length_too_short(monkeypatch):
    """Row has fewer than 5 columns."""

    def _mock_get(url, timeout):
        return MockResponse(json_data=[["a", "b", "c"]])  # only 3 entries

    monkeypatch.setattr(requests, "get", _mock_get)
    return _mock_get


@pytest.fixture
def _mock_get_row_wrong_length_too_long(monkeypatch):
    """Row has more than 5 columns."""

    def _mock_get(url, timeout):
        return MockResponse(json_data=[["a", "b", "c", "d", "e", "f"]])  # 6 entries

    monkeypatch.setattr(requests, "get", _mock_get)
    return _mock_get
