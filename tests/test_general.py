# Copyright 2023-2026 Airbus, CS Group
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

"""Unit tests for utils module."""

import pytest
from rs_server_common.utils.pytest import pytest_common_tests

from tests.test_authentication import CLUSTER_MODE, ROUTER_PREFIX_AUXIP


# Use cluster mode so we check the SessionMiddleware
@pytest.mark.parametrize(
    "fastapi_app",
    [
        {**CLUSTER_MODE, **ROUTER_PREFIX_AUXIP},
    ],
    indirect=["fastapi_app"],
    ids=[""],
)
def test_middleware_order(client):
    """Check that the FastAPI application middlewares were inserted in the right order."""
    pytest_common_tests.test_middleware_order(client, use_auth_middleware=False)


def test_handle_exceptions_middleware(client, mocker):
    """Test that HandleExceptionsMiddleware handles and logs errors as expected."""
    pytest_common_tests.test_handle_exceptions_middleware(client, mocker)
