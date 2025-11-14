# Copyright 2025 CS Group
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

"""Unit tests for settings module."""

import pytest
from _pytest.monkeypatch import MonkeyPatch
from rs_server_common.settings import docs_params


def test_docs_params_default(monkeypatch: MonkeyPatch):
    """
    Test that docs_params() returns the default values.

    Args:
        monkeypatch (MonkeyPatch): pytest's MonkeyPatch fixture used to temporarily remove the
            "RSPY_DOCS_URL" environment variable for this test.
    """
    monkeypatch.delenv("RSPY_DOCS_URL", raising=False)
    result = docs_params()
    assert result == {"docs_url": "/api.html", "openapi_url": "/api"}


@pytest.mark.parametrize(
    "env_value, expected",
    [
        ("docs", {"docs_url": "/docs", "openapi_url": "/docs/openapi.json"}),
        ("/docs/", {"docs_url": "/docs", "openapi_url": "/docs/openapi.json"}),
        ("//my/path//", {"docs_url": "/my/path", "openapi_url": "/my/path/openapi.json"}),
        ("", {"docs_url": "/", "openapi_url": "//openapi.json"}),
    ],
)
def test_docs_params_with_env(monkeypatch: MonkeyPatch, env_value: str, expected: dict[str, str]):
    """
    Test that docs_params() uses the RSPY_DOCS_URL environment variable.

    Args:
        monkeypatch : MonkeyPatch
            pytest's MonkeyPatch fixture used to temporarily set the
            "RSPY_DOCS_URL" environment variable for each test case.
        env_value : str
            The value assigned to the "RSPY_DOCS_URL" environment variable.
            May contain leading/trailing slashes or be empty.
        expected : dict[str, str]
            The expected dictionary output from docs_params() for the given
            env_value.
    """
    monkeypatch.setenv("RSPY_DOCS_URL", env_value)
    result = docs_params()
    assert result == expected
