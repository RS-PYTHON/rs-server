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

"""
ExternalAuthenticationConfig implementation.
"""
from dataclasses import dataclass
from typing import Any

from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)


@dataclass
class ExternalAuthenticationConfig:  # pylint: disable=too-many-instance-attributes
    """
    A configuration class for storing external authentication details, such as those used for
    API requiring token-based authentication.

    Values are read either from the rs-server.yaml (in local mode) or RSPY__TOKEN__ env vars (in cluster mode).

    Attributes:
        station_id (str): The unique identifier for the station requesting the token.
        domain (str): The domain for the external service.
        service_name (str): The name of the external service.
        service_url (str): The URL of the external service.
        auth_type (str): The type of authentication used (e.g., 'token', 'basic').
        token_url (str): The URL to request the authentication token.
        grant_type (str): The grant type used for obtaining the token. Currently, only 'password' is available.
        username (str): The username used for authentication.
        password (str): The password used for authentication.
        client_id (str): The client ID used for authentication.
        client_secret (str): The client secret used for authentication.
        scope (Optional[str]): The scope of access requested in the authentication token (if applicable).
        authorization (Optional[str]): Additional authorization header (if required).
        trusted_domains (Optional[str]): The list of allowed hosts for http redirection
    """

    station_id: str
    domain: str
    service_name: str
    service_url: str
    auth_type: str
    token_url: str
    grant_type: str
    username: str
    password: str
    client_id: str
    client_secret: str
    scope: str | None = None
    authorization: str | None = None
    trusted_domains: list[str] | None = None


def create_external_auth_config(
    station_id: str,
    station_dict: dict[str, Any],
    service_dict: dict[str, Any],
) -> ExternalAuthenticationConfig | None:
    """
    Create an ExternalAuthenticationConfig object based on the provided station and service dictionaries.

    Args:
        station_id (str): The unique identifier for the station.
        station_dict (Dict[str, Any]): Dictionary containing station-specific configuration details.
        service_dict (Dict[str, Any]): Dictionary containing service-specific configuration details.

    Returns:
        ExternalAuthenticationConfig: An object representing the external authentication configuration.

    Raises:
        KeyError: If any required keys are missing in the configuration dictionaries.
    """
    try:
        return ExternalAuthenticationConfig(
            station_id=station_id,
            domain=station_dict["domain"],
            service_name=service_dict["name"],
            service_url=service_dict["url"],
            auth_type=station_dict.get("authentication", {}).get("auth_type"),
            token_url=station_dict.get("authentication", {}).get("token_url"),
            grant_type=station_dict.get("authentication", {}).get("grant_type"),
            username=station_dict.get("authentication", {}).get("username"),
            password=station_dict.get("authentication", {}).get("password"),
            client_id=station_dict.get("authentication", {}).get("client_id"),
            client_secret=station_dict.get("authentication", {}).get("client_secret"),
            scope=station_dict.get("authentication", {}).get("scope"),
            authorization=station_dict.get("authentication", {}).get("authorization"),
            trusted_domains=station_dict.get("trusteddomains", None),
        )
    except KeyError as e:
        logger.error(f"Error loading configuration, couldn't find a key: {e}")
    return None
