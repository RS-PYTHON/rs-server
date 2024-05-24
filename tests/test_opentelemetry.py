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

from fastapi import FastAPI
from rs_server_common.utils import opentelemetry
from rs_server_common.utils.logging import Logging


async def test_opentelemetry(mocker):
    """
    For now, just test that the otel init code passes without errors.
    Don't check the generated logs, traces and metrics.
    """

    # Patch the global variables. See: https://stackoverflow.com/a/69685866
    mocker.patch("rs_server_common.utils.opentelemetry.FROM_PYTEST", new=True, autospec=False)

    Logging.default(__name__)
    app = FastAPI()
    opentelemetry.init_traces(app, "pytest")
