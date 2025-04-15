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
Authentication token for the staging.
"""

import copy
import datetime
import os
import re
from typing import Any

import requests
from fastapi import HTTPException
from requests.auth import AuthBase
from rs_server_common.authentication.external_authentication_config import (
    ExternalAuthenticationConfig,
)
from rs_server_common.utils import utils2
from rs_server_common.utils.logging import Logging
from starlette.requests import Request
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

logger = Logging.default(__name__)


def log_http_exception(*args, **kwargs) -> type[HTTPException]:
    """Log error and return an HTTP execption to be raised by the caller"""
    return utils2.log_http_exception(logger, *args, **kwargs)


HEADER_CONTENT_TYPE = "application/x-www-form-urlencoded"

# Mandatory attributed that should be present in the token dictionary
# Caution: there are more attributed than the information returned by
# the station response because we also add the creation date of the
# access and refresh token in addition to the station response.
MANDATORY_TOKEN_ATTRS = [
    "access_token",
    "access_token_creation_date",
    "expires_in",
    "refresh_token",
    "refresh_token_creation_date",
    "refresh_expires_in",
]


class TokenDataNotFound(HTTPException):
    """Raised if there are missing data in the dictionary to handle information about the token"""


# Custom authentication class
class TokenAuth(AuthBase):
    """Custom authentication class

    Args:
        AuthBase (ABC): Base auth class
    """

    def __init__(self, token: str):
        """Init token auth

        Args:
            token (str): Token value
        """
        self.token = token

    def __call__(self, request: Request):  # type: ignore
        """Add the Authorization header to the request

        Args:
            request (Request): request to be modified

        Returns:
            Request: request with modified headers
        """
        request.headers["Authorization"] = f"Bearer {self.token}"  # type: ignore
        return request

    def __repr__(self) -> str:
        return "RSPY Token handler"


def prepare_data(external_auth_config: ExternalAuthenticationConfig, call_refresh: bool) -> dict[str, str]:
    """Prepare data for token requests based on authentication configuration.

    Args:
        external_auth_config (ExternalAuthenticationConfig): Configuration object containing authentication details.

    Returns:
        Dict[str, str]: Dictionary containing the prepared data for the request.
    """
    data_to_send = {"client_id": external_auth_config.client_id, "client_secret": external_auth_config.client_secret}
    if call_refresh:
        data_to_send["grant_type"] = "refresh_token"
    else:
        data_to_send.update(
            {
                "grant_type": external_auth_config.grant_type,
                "username": external_auth_config.username,
                "password": external_auth_config.password,
            },
        )
        if external_auth_config.scope:
            data_to_send["scope"] = external_auth_config.scope

    return data_to_send


def prepare_headers(external_auth_config: ExternalAuthenticationConfig) -> dict[str, str]:
    """Prepare HTTP headers for token requests.

    Args:
        external_auth_config (ExternalAuthenticationConfig): Configuration object containing authentication details.

    Returns:
        Dict[str, str]: Dictionary containing the prepared headers.
    """
    headers = {"Content-Type": HEADER_CONTENT_TYPE}
    # Add Authorization header if it exists
    if external_auth_config.authorization:
        headers["Authorization"] = external_auth_config.authorization
    return headers


def validate_token_dict(token_dict: Any, config: ExternalAuthenticationConfig):
    """
    Check if the token variable contains the mandatory attributes

    Args:
        token_dict (Any):
        config (ExternalAuthenticationConfig):
          external_auth_config (ExternalAuthenticationConfig): The configuration object loaded
        from the rs-server.yaml file.
        token_dict (Dict): dictionary containing information about the current token
        information of the current token used to request data on the current station
    """
    if not token_dict:
        return

    for attr in MANDATORY_TOKEN_ATTRS:
        if attr not in token_dict:
            raise log_http_exception(
                HTTP_500_INTERNAL_SERVER_ERROR,
                f"Mandatory attribute {attr} is not defined in the token variable "
                f"of the station {config.station_id}!",
                None,
                TokenDataNotFound,
            )
        if not token_dict[attr]:
            raise log_http_exception(
                HTTP_500_INTERNAL_SERVER_ERROR,
                f"Token variable attribute {attr} of the station {config.station_id} is None !",
                None,
                TokenDataNotFound,
            )
    for attr in "access_token", "refresh_token":
        validate_token_format(attr)


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
        raise log_http_exception(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Invalid token format received from the station.",
        )


def __request_token(external_auth_config: ExternalAuthenticationConfig, data_to_send: dict[str, str]):
    """
    Subfunction of get_station_token. Request either access or refresh token.
    """
    try:
        response = requests.post(
            external_auth_config.token_url,
            data=data_to_send,
            timeout=5,
            headers=prepare_headers(external_auth_config),
        )
    except requests.exceptions.RequestException as e:
        raise log_http_exception(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Request to token endpoint failed: {str(e)}",
        ) from e

    # Check response status
    if response.status_code != HTTP_200_OK:
        raise log_http_exception(
            status_code=response.status_code,
            detail=f"Failed to get the token from the station {external_auth_config.station_id}. "
            f"Response from the station: {response.text or ''}",
        )

    return response.json()


def get_station_token(external_auth_config: ExternalAuthenticationConfig, original_token_dict: dict) -> dict:
    """
    Retrieve and validate an authentication token for a specific station and service.
    Thee are two main use cases:
        - If the token shared variable is empty, it means that we don't have any token for now
          so we will retrieve one by requesting the authorisation server of the station
        - If the token shared variable is not empty, it means we already have a token. If it
          is still valid, we use it to request data to the resource server of the station.
          If it is not valid anymore, we use the refresh token to request a new token to
          the authorisation server

    Args:
        external_auth_config (ExternalAuthenticationConfig): The configuration object loaded
        from the rs-server.yaml file.
        token_var (dask.distributed.Variable): variable shared between all workers containing
        information of the current token used to request data on the current station

    Returns:
        str: The token as string.

    Raises:
        HTTPException: If the external authentication configuration cannot be retrieved,
                       if the token request fails, or if the token format is invalid.
    """
    if not external_auth_config:
        raise log_http_exception(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Failed to retrieve the configuration for the station token.",
        )
    token_dict = copy.deepcopy(original_token_dict)
    # If no tokens are yet registered, we ask the authorisation server to generate one by providing
    # an "authorisation grant" to the authorisation server
    validate_token_dict(token_dict, external_auth_config)
    current_date = datetime.datetime.now()

    nb_secs_before_token_exp = int(os.getenv("RSPY_TIME_BEFORE_ACCESS_TOKEN_EXPIRE", "60"))
    nb_secs_before_refresh_token_exp = int(os.getenv("RSPY_TIME_BEFORE_REFRESH_TOKEN_EXPIRE", "60"))

    # If we have no token yet or if both the access and refresh tokens are expired, we get a new token
    # using the authorisation grant
    if not token_dict or (
        token_dict
        and (current_date - token_dict["access_token_creation_date"]).total_seconds()
        > token_dict["expires_in"] - nb_secs_before_token_exp
        and (current_date - token_dict["refresh_token_creation_date"]).total_seconds()
        > token_dict["refresh_expires_in"] - nb_secs_before_refresh_token_exp
    ):
        if not token_dict:
            logger.info(
                f"""No existing token found -> fetching a new access token """
                f"""from station url: {external_auth_config.token_url}""",
            )
        else:
            logger.info(
                f"""Current access and refresh token expired -> fetching access token """
                f"""from station url: {external_auth_config.token_url}""",
            )

        # Get the new token and add its creation date
        data_to_send = prepare_data(external_auth_config, call_refresh=False)
        token_dict.update(__request_token(external_auth_config, data_to_send))
        token_dict["access_token_creation_date"] = token_dict["refresh_token_creation_date"] = datetime.datetime.now()

        logger.info(f"Access token retrieved from the station url: {external_auth_config.token_url} ")
        # Validate the token variable and then update the shared token
        validate_token_dict(token_dict, external_auth_config)

    else:
        # Check that the token variable contains the mandatory elements
        validate_token_dict(token_dict, external_auth_config)

        # If the current token expires in less than one minute, create a new request to send
        # to the authorisation server with the refresh token given in the payload of the request
        current_date = datetime.datetime.now()
        diff_in_sec = (current_date - token_dict["access_token_creation_date"]).total_seconds()

        if diff_in_sec > token_dict["expires_in"] - nb_secs_before_token_exp:
            logger.info("Current access_token is about to expire. Launching request to refresh the token...")

            data_to_send = prepare_data(external_auth_config, call_refresh=True)
            data_to_send.update({"refresh_token": token_dict["refresh_token"]})

            # Refresh the token and add the creation date of the newly created token
            token_dict.update(__request_token(external_auth_config, data_to_send))
            token_dict["access_token_creation_date"] = datetime.datetime.now()

            # Validate the new token dictionary and update the shared token variable with this dictionary
            validate_token_dict(token_dict, external_auth_config)
            logger.info("Access token has been successfully refreshed !")

    return token_dict
