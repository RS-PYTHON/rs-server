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
"""Module use for osam endpoints tests"""
import pytest
from starlette.status import HTTP_200_OK

@pytest.mark.asyncio
async def test_ping_endpoint(mocker, osam_client):
    """Test for live probe endpoint."""
    assert osam_client.get("/_mgmt/ping").status_code == HTTP_200_OK