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

"""Unit tests for OpenTelemetry."""

import requests
from fastapi import FastAPI
from requests.exceptions import ConnectionError as RequestsConnectionError
from rs_server_common.utils import init_opentelemetry
from rs_server_common.utils.logging import Logging


async def test_opentelemetry(mocker, monkeypatch):
    """
    For now, just test that the otel init code passes without errors.
    Don't check the generated logs, traces and metrics.
    """

    # Patch the global variables. See: https://stackoverflow.com/a/69685866
    mocker.patch("rs_server_common.utils.init_opentelemetry.FROM_PYTEST", new=True, autospec=False)

    # Patch the env variables
    monkeypatch.setenv("OTEL_PYTHON_REQUESTS_TRACE_HEADERS", "1")
    monkeypatch.setenv("OTEL_PYTHON_REQUESTS_TRACE_BODY", "1")

    Logging.default(__name__)
    app = FastAPI()
    init_opentelemetry.init_traces(app, "pytest")

    # Run a dummy http request to be instrumented by opentelemetry
    try:
        requests.get("http://dummy", timeout=1)
    except RequestsConnectionError:
        pass
