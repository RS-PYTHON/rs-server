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
# pylint: disable=too-many-lines

"""Test module for token authentication."""

import requests
from rs_server_common.authentication.token_auth import TokenAuth


class TestTokenAuth:
    """Class with tests for token auth."""

    def test_token_auth_init(self):
        """Test that the TokenAuth initializes with the correct token."""
        test_value_tkn = "my_test_token"
        auth = TokenAuth(test_value_tkn)
        assert auth.token == test_value_tkn

    def test_token_auth_call(self, mocker):
        """Test that TokenAuth modifies the request headers crrectly."""
        test_value_tkn = "my_test_token"
        auth = TokenAuth(test_value_tkn)

        # Mocking the request object using mocker
        request = mocker.Mock(spec=requests.Request)  # type: ignore
        request.headers = {}

        # Call the auth object with the request
        modified_request = auth(request)

        # Ensure headers were modified correctly
        assert modified_request.headers["Authorization"] == f"Bearer {test_value_tkn}"

    def test_token_auth_repr(self):
        """Test the repr_ method of TokenAuth."""
        auth = TokenAuth("my_test_token")
        assert repr(auth) == "RSPY Token handler"
