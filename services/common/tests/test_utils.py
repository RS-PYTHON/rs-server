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

"""Unit tests for utility funtions."""

import requests
import responses
from rs_server_common.utils.utils2 import read_response_error


@responses.activate
def test_response_error():
    """Test reading responses errors."""

    dummy_href = "http://DUMMY_HREF"
    detail = "detail message"
    error = "error message"
    content = "response content"
    timeout = 10  # seconds

    responses.get(url=dummy_href, status=500, json={"detail": detail})
    assert read_response_error(requests.get(dummy_href, timeout=timeout)) == detail

    responses.get(url=dummy_href, status=500, json={"error": error})
    assert read_response_error(requests.get(dummy_href, timeout=timeout)) == error

    responses.get(url=dummy_href, status=500, body=content)
    assert read_response_error(requests.get(dummy_href, timeout=timeout)) == content
