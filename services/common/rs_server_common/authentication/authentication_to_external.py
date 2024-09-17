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
Authentication to external station module
"""

import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
import yaml
from fastapi import HTTPException
from rs_server_common.settings import env_bool
from rs_server_common.utils.logging import Logging
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

logger = Logging.default(__name__)

CONFIG_FILENAME = "rs-server.yaml"
DEFAULT_CONFIG_PATH_AUTH_TO_EXTERNAL = f"{os.path.expanduser('~')}/.config/{CONFIG_FILENAME}"
ACCESS_TK_KEY_IN_RESPONSE = "access_token"
# if CLUSTER_MODE, the file ~/.config/rs-server.yaml has to be created, once, when the pod starts


def create_rs_server_config_yaml():
    """
    Create the rs-server configuration YAML file from environment variables.

    The environment variables must follow the pattern:
    RSPY__TOKEN__<service>__<station>__<section_name>__<rest_of_the_info_for_key>

    The YAML file is saved to ~/.config/rs-server.yaml by default.
    """
    # read all the env vars. The pattern for all the env vars used is:
    # RSPY__TOKEN__<service>__<station>__<section_name>__<rest of the info for key>
    # Regular expression to match the pattern RSPY__TOKEN__<service>__<station>__<section>__<rest_of_the_key>
    pattern = r"^RSPY__TOKEN__([^__]+)__([^__]+)__([^__]+)(__.*)?$"
    config_data: Dict[str, Any] = {}

    # Iterate over all environment variables
    for var, value in os.environ.items():
        match = re.match(pattern, var)

        if match:
            # Extract service, station, section, and rest_of_key from the environment variable
            # Convert to lowercase for YAML formatting
            try:
                service, station, section, rest_of_key = (s.lower() if s else "" for s in match.groups())
            except ValueError:
                logger.warning(
                    f"The environment variable {var} does not contain enough values to be unpacked. "
                    "Disregarding this variable.",
                )
                continue

            # Initialize with mandatory fields the station entry if it doesn't exist
            rest_of_key = rest_of_key.strip("__").replace("__", "_") if rest_of_key else None
            station_data = config_data.setdefault(station, {"service": {"name": service}})
            if rest_of_key:
                section_data = station_data.setdefault(section, {})
                section_data[rest_of_key] = value
            else:
                station_data[section] = value
    try:
        # Create the directory if it doesn't exist
        os.makedirs(os.path.dirname(DEFAULT_CONFIG_PATH_AUTH_TO_EXTERNAL), exist_ok=True)

        # Write the YAML data to the file
        main_dict = {"external_data_sources": config_data}
        with open(DEFAULT_CONFIG_PATH_AUTH_TO_EXTERNAL, "w", encoding="utf-8") as yaml_file:
            yaml.dump(main_dict, yaml_file, default_flow_style=False)
        logger.info(f"Configuration successfully written to {DEFAULT_CONFIG_PATH_AUTH_TO_EXTERNAL}")
    except (OSError, IOError) as e:
        logger.exception(f"Failed to write configuration to {DEFAULT_CONFIG_PATH_AUTH_TO_EXTERNAL}: {e}")
        raise RuntimeError(f"Failed to write configuration to {DEFAULT_CONFIG_PATH_AUTH_TO_EXTERNAL}: {e}") from e


@dataclass
class ExternalAuthenticationConfig:  # pylint: disable=too-many-instance-attributes
    """
    A configuration class for storing external authentication details, such as those used for
    API requiring token-based authentication.

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


def get_station_token(external_auth_config: ExternalAuthenticationConfig) -> str:
    """
    Retrieve and validate an authentication token for a specific station and service.

    Args:
        external_auth_config (ExternalAuthenticationConfig): The configuration object loaded
        from the rs-server.yaml file.

    Returns:
        str: The token as string.

    Raises:
        HTTPException: If the external authentication configuration cannot be retrieved,
                       if the token request fails, or if the token format is invalid.
    """
    if not external_auth_config:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Could not retrieve the configuration for the station token.",
        )

    headers = prepare_headers(external_auth_config)
    data_to_send = prepare_data(external_auth_config)
    logger.info(f"Fetching access token from station url: {external_auth_config.token_url}")
    try:
        response = requests.post(
            external_auth_config.token_url,
            data=data_to_send,
            timeout=5,
            headers=headers,
        )
        if response.status_code != HTTP_200_OK:
            logger.error(
                f"Could not get the token from the station {external_auth_config.station_id}. "
                f"Response from the station: {response.text or ''}",
            )
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Could not get the token from the station {external_auth_config.station_id}. "
                f"Response from the station: {response.text or ''}",
            )
    except requests.exceptions.RequestException as e:
        logger.error(f"Request to token endpoint failed: {str(e)}")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Request to token endpoint failed: {str(e)}",
        ) from e

    token = response.json()
    # TODO: Is it worthy to validate it?
    # validate_token_format(token.get("access_token", ""))
    if ACCESS_TK_KEY_IN_RESPONSE not in token:
        logger.error(
            f"The token field was not found in the response from the station {external_auth_config.station_id}. ",
        )
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"The token field was not found in the response from the station {external_auth_config.station_id}.",
        )
    logger.info(f"Access token retrieved from the station url: {external_auth_config.token_url} ")
    return token.get("access_token")


def prepare_headers(external_auth_config: ExternalAuthenticationConfig) -> Dict[str, str]:
    """Prepare HTTP headers for token requests.

    Args:
        external_auth_config (ExternalAuthenticationConfig): Configuration object containing authentication details.

    Returns:
        Dict[str, str]: Dictionary containing the prepared headers.
    """
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    # Add Authorization header if it exists
    if external_auth_config.authorization:
        headers["Authorization"] = external_auth_config.authorization
    return headers


def prepare_data(external_auth_config: ExternalAuthenticationConfig) -> Dict[str, str]:
    """Prepare data for token requests based on authentication configuration.

    Args:
        external_auth_config (ExternalAuthenticationConfig): Configuration object containing authentication details.

    Returns:
        Dict[str, str]: Dictionary containing the prepared data for the request.
    """
    data_to_send = {
        "client_id": external_auth_config.client_id,
        "client_secret": external_auth_config.client_secret,
        "grant_type": external_auth_config.grant_type,
        "username": external_auth_config.username,
        "password": external_auth_config.password,
    }
    if external_auth_config.scope:
        data_to_send["scope"] = external_auth_config.scope
    return data_to_send


def validate_token_format(token: str) -> None:
    """Validate the format of a given token.

    Args:
        token (str): The token string to be validated.

    Raises:
        HTTPException: If the token format does not match the expected pattern.
    """
    # Check if the token matches the expected format using a regular expression
    if not re.match(r"^[A-Za-z0-9\-_\.]+$", token):
        # Raise an HTTP exception if the token format is invalid
        logger.error("Invalid token format received from the station.")
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Invalid token format received from the station.")


def load_external_auth_config_by_station_service(
    station_id: str,
    service: str,
    path: str | None = None,
) -> Optional[ExternalAuthenticationConfig]:
    """
    Load the external authentication configuration for a given station and service from a YAML file.

    Args:
        station_id (str): The ID of the station for which the authentication config is being loaded.
        service (str): The name of the service to load the authentication configuration for.

    Returns:
        Optional[ExternalAuthenticationConfig]: An object representing the external authentication configuration,
        or None if the station or service is not found or if an error occurs.

    Raises:
        FileNotFoundError: If the configuration file cannot be found.
        yaml.YAMLError: If there's an error parsing the YAML configuration file.
        Exception: For any unexpected errors during the loading process.
    """
    config_file = f"{path.rstrip('/')}/{CONFIG_FILENAME}" if path else DEFAULT_CONFIG_PATH_AUTH_TO_EXTERNAL

    try:
        with open(config_file, encoding="utf-8") as f:
            config_yaml = yaml.safe_load(f)

    except (FileNotFoundError, yaml.YAMLError) as e:
        logger.error(f"Error loading configuration: {e}")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error loading configuration. {e}",
        ) from e
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception(f"An unexpected error occurred: {e}")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred. {e}",
        ) from e

    # Retrieve station and service details from the YAML config
    station_dict = config_yaml.get("external_data_sources", {}).get(station_id, {})
    service_dict = station_dict.get("service", {})

    # Validate that the service name matches
    if service_dict.get("name") != service:
        logger.warning(f"No matching service found for station_id: {station_id} and service: {service}")
        return None

    # Create and return the ExternalAuthenticationConfig object
    return create_external_auth_config(station_id, station_dict, service_dict)


def load_external_auth_config_by_domain(domain: str, path: str | None = None) -> Optional[ExternalAuthenticationConfig]:
    """
    Load the external authentication configuration based on the domain from a YAML file.

    Args:
        domain (str): The domain to search for in the authentication configuration.

    Returns:
        Optional[ExternalAuthenticationConfig]: An object representing the external authentication configuration,
        or None if no matching domain is found or if an error occurs.

    Raises:
        FileNotFoundError: If the configuration file cannot be found.
        yaml.YAMLError: If there's an error parsing the YAML configuration file.
        Exception: For any unexpected errors during the loading process.
    """
    config_file = path.rstrip("/") + f"/{CONFIG_FILENAME}" if path else DEFAULT_CONFIG_PATH_AUTH_TO_EXTERNAL
    try:
        with open(config_file, encoding="utf-8") as f:
            config_yaml = yaml.safe_load(f)
            logger.info(f"Loaded configuration YAML: {config_yaml}")

            # Iterate through the external data sources in the configuration
            for station_id, station_dict in config_yaml.get("external_data_sources", {}).items():
                if station_dict.get("domain") == domain:
                    return create_external_auth_config(station_id, station_dict, station_dict.get("service", {}))

    except (FileNotFoundError, yaml.YAMLError) as e:
        logger.error(f"Error loading configuration: {e}")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error loading configuration. {e}",
        ) from e
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception(f"An unexpected error occurred: {e}")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred. {e}",
        ) from e

    return None


def create_external_auth_config(
    station_id: str,
    station_dict: Dict[str, Any],
    service_dict: Dict[str, Any],
) -> Optional[ExternalAuthenticationConfig]:
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
        )
    except KeyError as e:
        logger.error(f"Error loading configuration, couldn't find a key: {e}")
    return None


def set_eodag_auth_env(ext_auth_config: ExternalAuthenticationConfig):
    """Set the authorization env vars for eodag"""
    # mandatory keys
    os.environ[f"EODAG__{ext_auth_config.station_id}__auth__auth_uri"] = ext_auth_config.token_url
    os.environ[f"EODAG__{ext_auth_config.station_id}__auth__req_data__client_id"] = ext_auth_config.client_id
    os.environ[f"EODAG__{ext_auth_config.station_id}__auth__req_data__client_secret"] = ext_auth_config.client_secret
    os.environ[f"EODAG__{ext_auth_config.station_id}__auth__req_data__username"] = ext_auth_config.username
    os.environ[f"EODAG__{ext_auth_config.station_id}__auth__req_data__password"] = ext_auth_config.password
    os.environ[f"EODAG__{ext_auth_config.station_id}__auth__req_data__grant_type"] = ext_auth_config.grant_type
    # optional keys
    # NOTE: the Authorization cannot be overwritten when EODAG is sending the POST request when getting the token
    # if ext_auth_config.authorization:
    #    os.environ[f"EODAG__{ext_auth_config.station_id}__auth__headers__authorization"] = \
    # ext_auth_config.authorization
    if ext_auth_config.scope:
        os.environ[f"EODAG__{ext_auth_config.station_id}__auth__req_data__scope"] = ext_auth_config.scope


def set_eodag_auth_token(
    station_id: str | None = None,
    service: str | None = None,
    domain: str | None = None,
    path: str | None = None,
) -> None:
    """
    Set the Authorization environment variable for EODAG using a token retrieved from the station.
    Either station_id and service OR domain may be enabled.
    Args:
        station_id (Optional[str]): The ID of the station for which the authorization token is set.
        service (Optional[str]): The service name used to retrieve the token.
        domain (Optional[str]): The domain related to the station for the token.

    Raises:
        ValueError: If the station_id is None or an empty string.
        Exception: If token retrieval fails for any reason, a general exception will be logged.
    """
    if station_id and service:
        ext_auth_config = load_external_auth_config_by_station_service(station_id.lower(), service, path)
    elif domain:
        ext_auth_config = load_external_auth_config_by_domain(domain, path)
    else:
        raise ValueError("Either station_id and service or domain must be provided.")

    if not ext_auth_config:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Could not retrieve the configuration for the station token.",
        )
    # call the module implemented for rspy-352
    # NOTE: the cadip_ws_config should be also configured
    if env_bool("RSPY_USE_MODULE_FOR_STATION_TOKEN", False):
        os.environ[f"EODAG__{ext_auth_config.station_id}__auth__credentials__token"] = get_station_token(
            ext_auth_config,
        )
    else:
        # use eodag to get the token
        # NOTE: the cadip_ws_config should be also configured
        set_eodag_auth_env(ext_auth_config)
