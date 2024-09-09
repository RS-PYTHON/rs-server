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

"""
This module is used to share common functions between apis endpoints.
Split it from utils.py because of dependency conflicts between rs-server-catalog and rs-server-common.
"""

from dataclasses import dataclass


@dataclass
class AuthInfo:
    """User authentication information in KeyCloak."""

    # User login (preferred username)
    user_login: str

    # IAM roles
    iam_roles: list[str]

    # Configuration associated to the API key (not implemented for now)
    apikey_config: dict


def read_response_error(response):
    """Read and return an HTTP response error detail."""

    # Try to read the response detail or error
    try:
        json = response.json()
        detail = json.get("detail") or json["error"]

    # If this fail, get the full response content
    except Exception:  # pylint: disable=broad-exception-caught
        detail = response.content.decode("utf-8", errors="ignore")

    return detail
