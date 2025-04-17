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
Authentication to external stations module.
"""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException
from rs_server_common import settings
from rs_server_common.authentication.external_authentication_config import (
    ExternalAuthenticationConfig,
    create_external_auth_config,
)
from rs_server_common.utils.logging import Logging
from starlette.status import (
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

logger = Logging.default(__name__)


class ServiceNotFound(Exception):
    """Raised if there are no existing service matching the provided domain"""


def __read_configuration() -> dict:  # pylint: disable=too-many-locals
    """
    Read the rs-server configuration for authentication to extenal stations.

    In local mode, we read an existing rs-server.yaml local file, either customized by the user
    or released with the source code.

    In cluster mode, we read the environment variables with the pattern:
    RSPY__TOKEN__<service>__<station>__<section_name>__<rest_of_the_info_for_key>

    Returns:
        dict: A dictionary containing the configuration data

    Raises:
        HTTPException:
            - If the configuration file cannot be found (`FileNotFoundError`).
            - If there is an error in reading or parsing the YAML file (`yaml.YAMLError`).
            - For any other unexpected errors that occur during the file reading process.
    """
    config_data: dict[str, Any] = {}

    if settings.LOCAL_MODE:

        # In local mode, if this local file exists, it means it could be customized by the user, so we use it.
        path = f"{os.path.expanduser('~')}/.config/rs-server.yaml"

        # Else we use the default file released with the source code.
        if not os.path.isfile(path):
            path = str((Path(__file__).parent.parent.parent / "config/rs-server.yaml").resolve())

        try:

            # Open the configuration file and load the YAML content
            with open(path, encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            # Ensure the loaded configuration is a dictionary
            if not isinstance(config_data, dict):
                logger.error(msg := "Error loading the configuration for external stations authentication")
                raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

            return config_data

        except (FileNotFoundError, yaml.YAMLError) as e:
            logger.error(msg := f"Error loading configuration: {e}")
            raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=msg) from e
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.exception(msg := f"An unexpected error occurred: {e}")
            raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=msg) from e

    # Else, we are in cluster mode

    # Read all the env vars. The pattern for all the env vars used is:
    # RSPY__TOKEN__<service>__<station>__<section_name>__<rest of the info for key>
    # Regular expression to match the pattern RSPY__TOKEN__<service>__<station>__<section>__<rest_of_the_key>
    pattern = r"^RSPY__TOKEN__([^__]+)__([^__]+)__([^__]+)(__.*)?$"

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
            # Initialize a variable for the final processed value
            processed_value: Any = value
            # Check if the value looks like a list
            if value.startswith("[") and value.endswith("]"):
                try:
                    processed_value = [
                        domain.strip(" \"'") for domain in value.strip("[]").split(",")  # Remove whitespace and quotes
                    ]
                except Exception as e:  # pylint: disable=broad-except
                    logger.error(f"Failed to parse list value for {var}: {value}. Error: {e}")
                    raise RuntimeError(f"Failed to parse list value for {var}: {value}. Error: {e}") from e

            if rest_of_key:
                section_data = station_data.setdefault(section, {})
                section_data[rest_of_key] = processed_value
            else:
                station_data[section] = processed_value

    return {"external_data_sources": config_data}


# Read the configuration only once
CONFIGURATION: dict = __read_configuration()


def load_external_auth_config_by_station_service(
    station_id: str,
    service: str | None = None,
) -> ExternalAuthenticationConfig | None:
    """
    Load the external authentication configuration for a given station and service from a YAML file.

    Args:
        station_id (str): The ID of the station for which the authentication config is being loaded.
        service (str): The name of the service ("auxip" or "cadip") to load the authentication configuration for.

    Returns:
        Optional[ExternalAuthenticationConfig]: An object representing the external authentication configuration,
        or None if the station or service is not found or if an error occurs.

    """

    # check if the station_id has 'session', this is a particular case for cadip
    raw_station_id = station_id.replace("_session", "")

    # Retrieve station and service details from the YAML config
    station_dict = CONFIGURATION.get("external_data_sources", {}).get(raw_station_id, {})
    service_dict = station_dict.get("service", {})

    # Validate that the service name matches
    try:
        if service and service_dict.get("name") != service:
            logger.warning(f"No matching service found for station_id: {raw_station_id} and service: {service}")
            return None
    except KeyError:
        logger.exception("Failed to check the service name from configuration")
        return None

    # Create and return the ExternalAuthenticationConfig object
    return create_external_auth_config(station_id, station_dict, service_dict)


def load_external_auth_config_by_domain(domain: str) -> ExternalAuthenticationConfig | None:
    """
    Load the external authentication configuration based on the domain from a YAML file.

    Args:
        domain (str): The domain to search for in the authentication configuration.

    Returns:
        Optional[ExternalAuthenticationConfig]: An object representing the external authentication configuration,
        or None if no matching domain is found or if an error occurs.
    """

    # Iterate through the external data sources in the configuration
    for station_id, station_dict in CONFIGURATION.get("external_data_sources", {}).items():
        if station_dict.get("domain") == domain:
            return create_external_auth_config(station_id, station_dict, station_dict.get("service", {}))

    # Return an exception if there are no matching services for the given domain
    raise ServiceNotFound(f"No matching service found for domain: {domain}")


def load_external_auth_config(
    station_id: str | None = None,
    service: str | None = None,
    domain: str | None = None,
) -> ExternalAuthenticationConfig:
    """
    Load the external authentication configuration from a given station and service or from a domain.
    Args:
        station_id (Optional[str]): The ID of the station for which the authorization token is set.
        service (Optional[str]): The service name ("auxip" or "cadip") used to retrieve the token.
        domain (Optional[str]): The domain related to the station for the token.

    Raises:
        ValueError: If the station_id is None or an empty string.
        Exception: If token retrieval fails for any reason, a general exception will be logged.
    """
    if station_id and service:
        ext_auth_config = load_external_auth_config_by_station_service(station_id.lower(), service)
    elif domain:
        ext_auth_config = load_external_auth_config_by_domain(domain)
    else:
        raise ValueError("Either station_id and service or domain must be provided.")

    if not ext_auth_config:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Failed to retrieve the configuration for the station token.",
        )
    return ext_auth_config
