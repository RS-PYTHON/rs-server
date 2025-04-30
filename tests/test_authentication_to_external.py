# pylint: disable=too-many-lines

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

"""Unit tests for the authentication."""

import asyncio
import datetime
import json
import os
import re
from importlib import reload

import pytest
import responses
import yaml
from eodag.plugins.authentication.token import TokenAuth
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from rs_server_adgs import adgs_retriever, adgs_utils
from rs_server_cadip import cadip_retriever, cadip_utils
from rs_server_common.authentication import authentication_to_external
from rs_server_common.authentication.authentication_to_external import (
    ExternalAuthenticationConfig,
    create_external_auth_config,
    load_external_auth_config,
    load_external_auth_config_by_domain,
    load_external_auth_config_by_station_service,
)
from rs_server_common.authentication.token_auth import (
    TokenDataNotFound,
    get_station_token,
    prepare_data,
    prepare_headers,
    validate_token_format,
)
from rs_server_common.utils.logging import Logging
from starlette.status import HTTP_200_OK, HTTP_403_FORBIDDEN

from tests.app import ROUTER_PREFIX_AUXIP, ROUTER_PREFIX_CADIP

# Dummy url for the uac manager check endpoint
RSPY_UAC_CHECK_URL = "http://www.rspy-uac-manager.com"

# Dummy api key values
VALID_APIKEY = "VALID_API_KEY"
WRONG_APIKEY = "WRONG_APIKEY"

# Parametrize the fastapi_app fixture from conftest to enable authentication
CLUSTER_MODE = {"RSPY_LOCAL_MODE": False}

# Dummy token id
TOKEN = os.getenv("RSPY_TOKEN", "P4JSuo3gfQxKo0gfbQTb7nDn5OkzWP3umdGvy7G3CcI")

logger = Logging.default(__name__)


@pytest.mark.unit
@responses.activate
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
def test_get_station_token(get_external_auth_config, mock_token_dict):
    """Test retrieval of station token by station ID and service.

    This unit test checks the functionality of retrieving a station token using
    a mock external authentication configuration and HTTPXMock for simulating HTTP requests.

    Args:
        get_external_auth_config: Fixture to get an ExternalAuthenticationConfig object.
    """

    ext_auth_config = get_external_auth_config

    # ---------- Test error when no configuration object is provided
    with pytest.raises(HTTPException) as exc:
        get_station_token(None, {})
    assert "Failed to retrieve the configuration for the station token." in str(exc.value)

    # ---------- Test error when the token variable doesn't have all mandatory attributes
    # Simulate an invalid format of the token response from the authentication service
    response = {"unexpected_field": TOKEN, "token_type": "Bearer", "expires_in": 3600}
    responses.add(
        responses.POST,
        url=ext_auth_config.token_url,
        status=HTTP_200_OK,
        body=json.dumps(response),
    )
    with pytest.raises(TokenDataNotFound) as exc:
        get_station_token(ext_auth_config, {})
    assert (
        "Mandatory attribute access_token is not defined in the token variable of the station "
        f"{ext_auth_config.station_id}!"
    ) in str(exc.value)

    # ---------- Test valid token retrieval if we don't have any token yet
    # Simulate a token response from the authentication service
    response = mock_token_dict

    # We remove creation date because these information are not returned by the station
    # but only added in addition to the station response in the get_station_token method
    response.pop("access_token_creation_date")
    response.pop("refresh_token_creation_date")
    responses.add(
        responses.POST,
        url=ext_auth_config.token_url,
        status=HTTP_200_OK,
        body=json.dumps(response),
    )

    new_token = get_station_token(ext_auth_config, {})
    assert new_token["access_token"] == mock_token_dict["access_token"]

    # ---------- Test error when station responds with an error
    # Simulate a forbidden response from the station
    responses.add(
        responses.POST,
        url=ext_auth_config.token_url,
        status=HTTP_403_FORBIDDEN,
        body=json.dumps({"detail": "forbidden"}),
    )
    with pytest.raises(HTTPException) as exc:
        get_station_token(ext_auth_config, {})
    assert f"Failed to get the token from the station {ext_auth_config.station_id}" in str(exc.value)

    # ---------- Test to generate a new token using the refresh token when the current
    # access token is expired
    # Change the mock variable creation date and expiration date of the access token
    # to make it become unvalid
    mock_token_dict["access_token_creation_date"] = datetime.datetime(2023, 8, 15, 14, 30, 45)
    mock_token_dict["refresh_token_creation_date"] = datetime.datetime.now()

    response_new_valid_token = {
        "access_token": "NewFakeAccessToken",
        "expires_in": 3600,
        "refresh_token": "NewfakeRefreshToken",
        "refresh_expires_in": 7200,
        "token_type": "Bearer",
    }
    responses.add(
        responses.POST,
        url=ext_auth_config.token_url,
        status=HTTP_200_OK,
        body=json.dumps(response_new_valid_token),
    )
    new_token = get_station_token(ext_auth_config, mock_token_dict)

    # Check that the old token has been replaced with the new one
    assert new_token["access_token"] == response_new_valid_token["access_token"]

    # ---------- Test to generate a new token when both current access and refresh tokens are expired

    # Change the mock variable creation date and expiration date of both access and refresh tokens
    # to make them become unvalid
    mock_token_dict["access_token_creation_date"] = datetime.datetime(2023, 8, 15, 14, 30, 45)
    mock_token_dict["refresh_token_creation_date"] = datetime.datetime(2023, 8, 15, 14, 30, 45)

    response_new_valid_token = {
        "access_token": "NewFakeAccessToken",
        "expires_in": 3600,
        "refresh_token": "NewfakeRefreshToken",
        "refresh_expires_in": 7200,
        "token_type": "Bearer",
    }
    responses.add(
        responses.POST,
        url=ext_auth_config.token_url,
        status=HTTP_200_OK,
        body=json.dumps(response_new_valid_token),
    )
    new_token = get_station_token(ext_auth_config, mock_token_dict)
    # Check that the old token has been replaced with the new one
    assert new_token["refresh_token"] == response_new_valid_token["refresh_token"]


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
def test_prepare_headers(get_external_auth_config):
    """Test preparation of headers for authentication.

    This unit test checks the correct preparation of headers based on the external
    authentication configuration, with or without the authorization header.

    Args:
        get_external_auth_config: Fixture to get an ExternalAuthenticationConfig object.
    """
    ext_auth_config = get_external_auth_config
    # Test the prepare_headers function with the authorization header
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Authorization": "Basic test"}
    assert prepare_headers(ext_auth_config) == headers

    # Remove authorization and test again
    ext_auth_config.authorization = None
    del headers["Authorization"]

    # Test the prepare_headers function without the authorization header
    assert prepare_headers(ext_auth_config) == headers


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
@pytest.mark.parametrize("call_refresh", [True, False])
def test_prepare_data(get_external_auth_config, call_refresh):
    """Test preparation of data for authentication.

    This unit test checks the correct preparation of the data to be sent for retrieving a token
    based on the external authentication configuration loaded from the file.

    Args:
        get_external_auth_config: Fixture to get an ExternalAuthenticationConfig object.
    """
    ext_auth_config = get_external_auth_config
    # Expected data with the scope
    if call_refresh:
        data = {
            "client_id": "client_id",
            "client_secret": "client_secret",
            "grant_type": "refresh_token",
        }
    else:
        data = {
            "client_id": "client_id",
            "client_secret": "client_secret",
            "grant_type": "password",
            "username": "test",
            "password": "test",
            "scope": "openid",
        }

    # Test the prepare_data function with initial configuration
    assert prepare_data(ext_auth_config, call_refresh) == data

    # Update scope to None in the external authentication config and test again
    if not call_refresh:
        ext_auth_config.scope = None
        del data["scope"]

        # Test the prepare_data function after adding the scope
        assert prepare_data(ext_auth_config, call_refresh) == data


@pytest.mark.unit
def test_validate_token_format():
    """Test the validation of token format.

    This unit test verifies that valid tokens pass without exception, while invalid
    tokens raise an HTTPException with status code 400 and the appropriate error message.
    """
    # Test valid tokens (should not raise exceptions)
    valid_tokens = [
        "abc123",
        "P4JSuo3gfQxKo0gfbQTb7nDn5OkzWP3umdGvy7G3CcI",
        "aA0-_.",
    ]

    for token in valid_tokens:
        try:
            validate_token_format(token)  # Should not raise exception
        except HTTPException:
            pytest.fail(f"HTTPException raised for valid token: {token}")

    # Test invalid tokens (should raise exceptions)
    invalid_tokens = [
        "abc$",  # Invalid character ($)
        "a bc",  # Space in the token
        "!P4JSuo3gfQxKo0g",  # Invalid starting character (!)
        "abc@def",  # Invalid character (@)
    ]

    for token in invalid_tokens:
        with pytest.raises(HTTPException) as excinfo:
            validate_token_format(token)
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail == "Invalid token format received from the station."


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
def test_load_external_authentication_by_station_service_config_valid(mocker, get_external_auth_config):
    """
    Test successful loading of external authentication configuration for a given station and service.

    This test checks if the external authentication configuration is properly loaded when valid YAML
    configuration is provided. It mocks the content of a YAML file and verifies that the expected
    configuration is returned correctly.

    Args:
        mocker: Mocking framework.
        get_external_auth_config: Fixture providing an ExternalAuthenticationConfig object.

    Assertions:
        - The result is not None.
        - The returned configuration matches the mocked values for station_id, service_name, and domain.
    """
    # Mock the YAML content to simulate a valid configuration
    ext_auth_config = get_external_auth_config
    mock_yaml_content = f"""
    external_data_sources:
      {ext_auth_config.station_id}:
        domain: mockup-{ext_auth_config.service_name}-{ext_auth_config.station_id}.processing.svc.cluster.local
        service:
          name: {ext_auth_config.service_name}
          url: "http://test_url:6000"
        authentication:
          auth_type: oauth2
          token_url: http://test_url:6000/oauth2/token
          grant_type: password
          username: test
          password: test
          client_id: client_id
          client_secret: client_secret
          authorization: Basic test
    """
    mocker.patch(
        "rs_server_common.authentication.authentication_to_external.CONFIGURATION",
        yaml.safe_load(mock_yaml_content),
    )
    result = load_external_auth_config_by_station_service(ext_auth_config.station_id, ext_auth_config.service_name)
    assert result is not None
    assert result.station_id == ext_auth_config.station_id
    assert result.service_name == ext_auth_config.service_name
    assert (
        result.domain
        == f"mockup-{ext_auth_config.service_name}-{ext_auth_config.station_id}.processing.svc.cluster.local"
    )


@pytest.mark.unit
def test_load_external_auth_config_by_station_service_file_not_found(
    mocker,
):
    """
    Test error handling when configuration file is not found.

    This test simulates a `FileNotFoundError` and ensures that the correct HTTPException with a
    status code of 500 is raised when the configuration file is missing.

    Args:
        mocker: Mocking framework.
        station_id: The ID of the station being tested.

    Assertions:
        - HTTPException is raised with a status code of 500 and a relevant error message.
    """
    mocker.patch("builtins.open", side_effect=FileNotFoundError)
    with pytest.raises(HTTPException) as excinfo:
        reload(authentication_to_external)
    assert excinfo.value.status_code == 500
    assert "Error loading configuration" in excinfo.value.detail


@pytest.mark.unit
def test_load_external_auth_config_by_station_service_yaml_error(mocker):
    """
    Test error handling for invalid YAML format.

    This test ensures that when a YAML file with invalid formatting is loaded, a `YAMLError` is raised,
    and an appropriate HTTPException with a status code of 500 is returned. The logger should record an error.

    Args:
        mocker: Mocking framework.
        station_id: The ID of the station being tested.

    Assertions:
        - HTTPException is raised with a status code of 500 and relevant error details.
        - Logger error message is called once.
    """

    mocker.patch("builtins.open", mocker.mock_open(read_data="invalid: yaml: data"))
    mocker.patch(
        "yaml.safe_load",
        side_effect=yaml.YAMLError,
    )
    mock_logger = mocker.patch("rs_server_common.authentication.authentication_to_external.logger.error")
    with pytest.raises(HTTPException) as excinfo:
        reload(authentication_to_external)
    assert excinfo.value.status_code == 500
    assert "Error loading configuration" in excinfo.value.detail
    mock_logger.assert_called_once()


@pytest.mark.unit
def test_load_external_auth_config_by_station_service_unexpected_exception(mocker):
    """
    Test handling of an unexpected exception during configuration loading.

    This test simulates an unexpected error (generic Exception) during the configuration loading process
    and verifies that the correct HTTPException with status 500 and an appropriate error message is raised.
    The logger should record the exception.

    Args:
        mocker: Mocking framework.
        station_id: The ID of the station being tested.

    Assertions:
        - HTTPException is raised with status 500 and an appropriate error message.
        - Logger logs the exception.
    """
    mocker.patch("builtins.open", side_effect=Exception("Unexpected error"))
    mock_logger = mocker.patch("rs_server_common.authentication.authentication_to_external.logger.exception")
    with pytest.raises(HTTPException) as excinfo:
        reload(authentication_to_external)
    assert excinfo.value.status_code == 500
    assert "An unexpected error occurred" in excinfo.value.detail
    mock_logger.assert_called_once()


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
def test_load_external_auth_config_by_station_service_no_matching_service(mocker, station_id, get_external_auth_config):
    """
    Test scenario where no matching service is found for a given station.

    This test mocks a YAML file where the service does not match the expected service name for the station.
    It verifies that the function returns `None` and logs a warning indicating that no matching service
    was found.

    Args:
        mocker: Mocking framework.
        station_id: The ID of the station being tested.
        get_external_auth_config: Fixture providing an ExternalAuthenticationConfig object.

    Assertions:
        - Result is `None` if no matching service is found.
        - A warning is logged with appropriate details about the missing service.
    """
    # Mock the YAML content to simulate a valid configuration
    ext_auth_config = get_external_auth_config
    # Mock the YAML content where the service does not match
    mock_yaml_content = f"""
    external_data_sources:
      {ext_auth_config.station_id}:
        domain: mockup-{ext_auth_config.service_name}-{ext_auth_config.station_id}.processing.svc.cluster.local
        service:
          name: {ext_auth_config.service_name}
          url: "http://test_url:6000"
        authentication:
          auth_type: oauth2
          token_url: http://test_url:6000/oauth2/token
          grant_type: password
          username: test
          password: test
          client_id: client_id
          client_secret: client_secret
          authorization: Basic test
    """
    mocker.patch("builtins.open", mocker.mock_open(read_data=mock_yaml_content))
    mocker.patch(
        "yaml.safe_load",
        return_value=yaml.safe_load(mock_yaml_content),
    )
    mock_logger = mocker.patch("rs_server_common.authentication.authentication_to_external.logger.warning")
    result = load_external_auth_config_by_station_service(station_id, "unknwon_service")
    assert result is None
    mock_logger.assert_called_once_with(
        f"No matching service found for station_id: {station_id} and service: unknwon_service",
    )


@pytest.mark.unit
def test_load_external_auth_config_by_station_service_no_matching_station(mocker):
    """
    Test scenario where no matching station is found in the configuration.

    This test mocks a YAML configuration file with a known station, but simulates a request for an unknown station.
    It verifies that the function returns `None` and logs a warning indicating no matching station was found.

    Args:
        mocker: Mocking framework.

    Assertions:
        - Result is `None` if no matching station is found.
        - A warning is logged with details about the unknown station and service.
    """
    # Mock the YAML content where the service does not match
    mock_yaml_content = """
    external_data_sources:
      known_station:
        domain: mockup-known_service-known_station.processing.svc.cluster.local
        service:
          name: known_service}
          url: "http://test_url:6000"
        authentication:
          auth_type: oauth2
          token_url: http://test_url:6000/oauth2/token
          grant_type: password
          username: test
          password: test
          client_id: client_id
          client_secret: client_secret
          authorization: Basic test
    """
    mocker.patch("builtins.open", mocker.mock_open(read_data=mock_yaml_content))
    mocker.patch(
        "yaml.safe_load",
        return_value=yaml.safe_load(mock_yaml_content),
    )
    mock_logger = mocker.patch("rs_server_common.authentication.authentication_to_external.logger.warning")
    result = load_external_auth_config_by_station_service("unknown_station", "known_service")
    assert result is None
    mock_logger.assert_called_once_with(
        "No matching service found for station_id: unknown_station and service: known_service",
    )


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
def test_load_external_authentication_by_domain_config_valid(mocker, get_external_auth_config):
    """
    Test successful loading of external authentication configuration by domain.

    This test checks if the external authentication configuration is properly loaded when valid YAML
    configuration is provided based on the domain. It mocks the YAML content and verifies that the
    expected configuration is returned correctly.

    Args:
        mocker: Mocking framework.
        get_external_auth_config: Fixture providing an ExternalAuthenticationConfig object.

    Assertions:
        - The result is not `None`.
        - The returned configuration matches the mocked values for domain, station_id, and service_name.
    """
    # Mock the YAML content to simulate a valid configuration
    ext_auth_config = get_external_auth_config
    mock_yaml_content = f"""
    external_data_sources:
      {ext_auth_config.station_id}:
        domain: mockup-{ext_auth_config.service_name}-{ext_auth_config.station_id}.processing.svc.cluster.local
        service:
          name: {ext_auth_config.service_name}
          url: "http://test_url:6000"
        authentication:
          auth_type: oauth2
          token_url: http://test_url:6000/oauth2/token
          grant_type: password
          username: test
          password: test
          client_id: client_id
          client_secret: client_secret
          authorization: Basic test
    """
    mocker.patch(
        "rs_server_common.authentication.authentication_to_external.CONFIGURATION",
        yaml.safe_load(mock_yaml_content),
    )
    result = load_external_auth_config_by_domain(ext_auth_config.domain)
    assert result is not None
    assert result.station_id == ext_auth_config.station_id
    assert result.service_name == ext_auth_config.service_name
    assert (
        result.domain
        == f"mockup-{ext_auth_config.service_name}-{ext_auth_config.station_id}.processing.svc.cluster.local"
    )


@pytest.mark.unit
def test_load_external_auth_config_by_domain_file_not_found(mocker):
    """
    Test error handling when configuration file is not found by domain.

    This test simulates a `FileNotFoundError` when attempting to load a configuration file by domain.
    It verifies that the correct HTTPException with a status code of 500 is raised.

    Args:
        mocker: Mocking framework.

    Assertions:
        - HTTPException is raised with a status code of 500 and a relevant error message.
    """
    mocker.patch("builtins.open", side_effect=FileNotFoundError)
    with pytest.raises(HTTPException) as excinfo:
        reload(authentication_to_external)
    assert excinfo.value.status_code == 500
    assert "Error loading configuration" in excinfo.value.detail


@pytest.mark.unit
def test_load_external_auth_config_by_domain_yaml_error(mocker):
    """
    Test error handling for invalid YAML format when loading by domain.

    This test ensures that when a YAML file with invalid formatting is loaded by domain, a `YAMLError`
    is raised, and an appropriate HTTPException with a status code of 500 is returned. The logger should
    record an error.

    Args:
        mocker: Mocking framework.

    Assertions:
        - HTTPException is raised with a status code of 500 and relevant error details.
        - Logger error message is called once.
    """
    mocker.patch("builtins.open", mocker.mock_open(read_data="invalid: yaml: data"))
    mocker.patch(
        "yaml.safe_load",
        side_effect=yaml.YAMLError,
    )
    mock_logger = mocker.patch("rs_server_common.authentication.authentication_to_external.logger.error")
    with pytest.raises(HTTPException) as excinfo:
        reload(authentication_to_external)
    assert excinfo.value.status_code == 500
    assert "Error loading configuration" in excinfo.value.detail
    mock_logger.assert_called_once()


@pytest.mark.unit
def test_load_external_auth_config_by_domain_unexpected_exception(mocker):
    """
    Test handling of an unexpected exception during configuration loading by domain.

    This test simulates an unexpected error (generic Exception) during the configuration loading process
    by domain and verifies that the correct HTTPException with status 500 and an appropriate error message
    is raised. The logger should record the exception.

    Args:
        mocker: Mocking framework.

    Assertions:
        - HTTPException is raised with status 500 and an appropriate error message.
        - Logger logs the exception.
    """
    mocker.patch("builtins.open", side_effect=Exception("Unexpected error"))
    mock_logger = mocker.patch("rs_server_common.authentication.authentication_to_external.logger.exception")
    with pytest.raises(HTTPException) as excinfo:
        reload(authentication_to_external)
    assert excinfo.value.status_code == 500
    assert "An unexpected error occurred" in excinfo.value.detail
    mock_logger.assert_called_once()


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
def test_load_external_auth_config_by_domain_no_matching_domain(mocker, get_external_auth_config):
    """
    Test scenario where no matching domain is found in the configuration.

    This test mocks a YAML configuration where the requested domain does not match any available domains.
    It verifies that the function returns `None` if no matching domain is found.

    Args:
        mocker: Mocking framework.
        get_external_auth_config: Fixture providing an ExternalAuthenticationConfig object.

    Assertions:
        - Result is `None` if no matching domain is found.
    """

    # Mock the YAML content to simulate a valid configuration
    ext_auth_config = get_external_auth_config
    # Mock the YAML content where the service does not match
    mock_yaml_content = f"""
    external_data_sources:
      {ext_auth_config.station_id}:
        domain: mockup-{ext_auth_config.service_name}-{ext_auth_config.station_id}.processing.svc.cluster.local
        service:
          name: {ext_auth_config.service_name}
          url: "http://test_url:6000"
        authentication:
          auth_type: oauth2
          token_url: http://test_url:6000/oauth2/token
          grant_type: password
          username: test
          password: test
          client_id: client_id
          client_secret: client_secret
          authorization: Basic test
    """
    mocker.patch("builtins.open", mocker.mock_open(read_data=mock_yaml_content))
    mocker.patch(
        "yaml.safe_load",
        return_value=yaml.safe_load(mock_yaml_content),
    )
    domain = "unknwon_domain"
    with pytest.raises(authentication_to_external.ServiceNotFound) as exc:
        load_external_auth_config_by_domain(domain)
    assert f"No matching service found for domain: {domain}" in str(
        exc.value,
    )


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
def test_create_external_auth_config(get_external_auth_config):
    """
    Unit test for the create_external_auth_config function.

    This test verifies that a valid external authentication configuration is successfully created
    using mock YAML content that simulates both matching and non-matching service configurations.

    Args:
        get_external_auth_config: Fixture that returns a valid ExternalAuthenticationConfig object.

    The test validates:
    - The returned result is not None.
    - The result is an instance of ExternalAuthenticationConfig.
    - All fields of the configuration (e.g., station_id, domain, service details, authentication details)
      match the expected values.
    """
    # Mock the YAML content to simulate a valid configuration
    ext_auth_config = get_external_auth_config
    # Mock the YAML content where the service does not match
    station_dict = {
        "domain": ext_auth_config.domain,
        "authentication": {
            "auth_type": ext_auth_config.auth_type,
            "token_url": ext_auth_config.token_url,
            "grant_type": ext_auth_config.grant_type,
            "username": ext_auth_config.username,
            "password": ext_auth_config.password,
            "client_id": ext_auth_config.client_id,
            "client_secret": ext_auth_config.client_secret,
            "scope": ext_auth_config.scope,
            "authorization": ext_auth_config.authorization,
        },
    }
    service_dict = {
        "name": ext_auth_config.service_name,
        "url": ext_auth_config.service_url,
    }

    result = create_external_auth_config(ext_auth_config.station_id, station_dict, service_dict)

    assert result is not None
    assert isinstance(result, ExternalAuthenticationConfig)
    assert result.station_id == ext_auth_config.station_id
    assert result.domain == ext_auth_config.domain
    assert result.service_name == ext_auth_config.service_name
    assert result.service_url == ext_auth_config.service_url
    assert result.auth_type == ext_auth_config.auth_type
    assert result.token_url == ext_auth_config.token_url
    assert result.grant_type == ext_auth_config.grant_type
    assert result.username == ext_auth_config.username
    assert result.password == ext_auth_config.password
    assert result.client_id == ext_auth_config.client_id
    assert result.client_secret == ext_auth_config.client_secret
    assert result.scope == ext_auth_config.scope
    assert result.authorization == ext_auth_config.authorization


@pytest.mark.unit
def test_create_external_auth_config_missing_keys(mocker):
    """
    Unit test for create_external_auth_config when required keys are missing in the configuration.

    This test checks how the function handles incomplete configurations by omitting the "domain" and
    "name" keys, which are essential for proper configuration creation.

    Args:
        mocker: Pytest fixture used to mock the logger.

    The test expects:
    - The result is None.
    - A logger error is triggered, indicating the missing key ('domain').
    """
    # Missing "domain" and "name" keys should trigger a KeyError
    station_dict = {"authentication": {"auth_type": "token"}}
    service_dict = {"url": "http://rspy_test.net/api"}

    mock_logger = mocker.patch("rs_server_common.authentication.external_authentication_config.logger.error")
    result = create_external_auth_config("adgs", station_dict, service_dict)

    assert result is None
    mock_logger.assert_called_once_with("Error loading configuration, couldn't find a key: 'domain'")


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
@pytest.mark.parametrize("with_scope", [True, False])
def test_set_eodag_auth_env_success(mocker, get_external_auth_config, station_id, with_scope):
    """
    Unit test for setting the EODAG environment with a valid authentication configuration.

    This test checks if the required environment is correctly set based on the
    ExternalAuthenticationConfig object.

    Args:
        mocker: Pytest fixture for patching and mocking.
        get_external_auth_config: Fixture that provides an ExternalAuthenticationConfig object.

    The test validates:
    - Environment is correctly set for the station's authentication details (e.g., auth_uri, client_id,
      client_secret, username, password, grant_type, scope).
    """
    # Modify the config to have no scope
    if not with_scope:
        get_external_auth_config.scope = None

    mocker.patch(
        "rs_server_common.authentication.authentication_to_external.load_external_auth_config_by_station_service",
        return_value=get_external_auth_config,
    )
    eodag_provider = (
        adgs_retriever.init_adgs_provider(station_id)
        if "adgs" in station_id
        else cadip_retriever.init_cadip_provider(station_id)
    )
    config = eodag_provider.client.providers_config[station_id]

    assert config.auth.auth_uri == get_external_auth_config.token_url
    assert config.auth.req_data["client_id"] == get_external_auth_config.client_id
    assert config.auth.req_data["client_secret"] == get_external_auth_config.client_secret
    assert config.auth.req_data["username"] == get_external_auth_config.username
    assert config.auth.req_data["password"] == get_external_auth_config.password
    assert config.auth.req_data["grant_type"] == get_external_auth_config.grant_type

    if with_scope:
        assert config.auth.req_data["scope"] == get_external_auth_config.scope
    else:
        assert "scope" not in config.auth.req_data


@pytest.mark.unit
@pytest.mark.parametrize("station_id", ["adgs", "ins"])
async def test_set_eodag_auth_token_by_station_and_service_success(
    mocker,
    monkeypatch,
    get_external_auth_config,
    mock_token_dict,
    station_id,
):
    """
    Unit test for setting the EODAG authentication token using station ID and service.

    This test checks the process of retrieving a station token and setting the corresponding
    environment variable using a mock external authentication configuration.

    Args:
        mocker: Pytest fixture for patching and mocking.
        get_external_auth_config: Fixture that provides an ExternalAuthenticationConfig object.

    The test verifies:
    - The token is correctly set in the environment variable when the internal token module is used.
    - When the internal token module is disabled, the EODAG environment variables are set correctly
      for authentication.
    """
    try:
        # Mock the env var RSPY_USE_MODULE_FOR_STATION_TOKEN to True. This will trigger the
        # usage of the internal token module  for getting the token and setting it to the eodag
        monkeypatch.setenv("RSPY_USE_MODULE_FOR_STATION_TOKEN", True)
        reload(adgs_retriever)
        reload(cadip_retriever)

        mocker.patch(
            "rs_server_common.authentication.authentication_to_external.load_external_auth_config_by_station_service",
            return_value=get_external_auth_config,
        )
        mocker.patch(
            "rs_server_common.data_retrieval.eodag_provider.get_station_token",
            return_value=mock_token_dict,
        )
        eodag_provider = (
            adgs_retriever.init_adgs_provider(station_id)
            if "adgs" in station_id
            else cadip_retriever.init_cadip_provider(station_id)
        )
        config = eodag_provider.client.providers_config[station_id]

        # Check if the correct token was set in the environment
        assert config.auth.credentials["token"] == mock_token_dict["access_token"]

    finally:
        # Restore default value
        monkeypatch.setenv("RSPY_USE_MODULE_FOR_STATION_TOKEN", False)
        reload(adgs_retriever)
        reload(cadip_retriever)

        # Call the function
        mock_set_env = mocker.patch(
            "rs_server_common.data_retrieval.eodag_provider.CustomEODataAccessGateway.authenticate_provider",
        )
        eodag_provider = (
            adgs_retriever.init_adgs_provider(station_id)
            if "adgs" in station_id
            else cadip_retriever.init_cadip_provider(station_id)
        )

        # Check if the correct values were set for the EODAG environment
        mock_set_env.assert_called_once_with(station_id, get_external_auth_config)


def test_set_eodag_auth_token_no_station_or_domain():
    """
    Unit test for error handling when neither station_id nor domain is provided.

    This test verifies that the load_external_auth_config function raises a ValueError when neither
    station_id/service nor domain is provided as input parameters.

    The test expects:
    - A ValueError is raised with a message indicating that either station_id/service or domain must be
      provided.
    """
    with pytest.raises(ValueError, match="Either station_id and service or domain must be provided."):
        load_external_auth_config(station_id=None, service=None, domain=None)


def test_set_eodag_auth_token_config_not_found(mocker):
    """
    Unit test for handling the case where no external authentication configuration is found.

    This test checks if the load_external_auth_config function correctly raises an HTTPException
    when the configuration for the station token cannot be retrieved.

    Args:
        mocker: Pytest fixture for patching and mocking.

    The test expects:
    - An HTTPException is raised with a 404 status code and a message indicating that the configuration
      could not be retrieved.
    """
    mocker.patch(
        "rs_server_common.authentication.authentication_to_external.load_external_auth_config_by_station_service",
        return_value=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        load_external_auth_config(station_id="adgs", service="auxip")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Failed to retrieve the configuration for the station token."


@responses.activate
@pytest.mark.parametrize(
    "fastapi_app, station_id",
    ((ROUTER_PREFIX_CADIP, "cadip"), (ROUTER_PREFIX_AUXIP, "adgs")),
    ids=["cadip", "adgs"],
    indirect=["fastapi_app"],
)
async def test_set_eodag_auth_token_called_once(  # pylint: disable=too-many-locals,too-many-statements
    mocker,
    monkeypatch,
    client,
    station_id,
    adgs_response,
    cadip_file_response,
    cadip_session_response,
):
    """Test that requesting an auxip/cadip auth token with eodag happens only once per station."""
    content_type = "application/json"
    r_headers = {"Content-Type": content_type}

    adgs = station_id == "adgs"
    cadip = station_id == "cadip"

    # Don't patch this env var, use the "true" (for local mode) eodag configuration
    monkeypatch.delenv("RSPY_ADGS_SEARCH_CONFIG")
    monkeypatch.delenv("RSPY_CADIP_SEARCH_CONFIG")

    # Read the search configuration yaml file
    search_yaml = adgs_utils.search_yaml if adgs else cadip_utils.search_yaml
    with open(search_yaml, encoding="utf-8") as opened:

        # Read collection list
        collections = yaml.safe_load(opened)["collections"]
        collection_ids = {collection["id"] for collection in collections}

        # Read eodag provider list = stations.
        # With cadip, only the token for _session providers are retrieved.
        suffix = "_session" if cadip else ""
        all_providers = sorted({collection["station"] + suffix for collection in collections})

    def mock_station_response(request):
        if adgs:
            body = adgs_response
        else:  # cadip
            if request.path_url.startswith("/Sessions"):
                body = cadip_session_response
            else:
                body = cadip_file_response
        return HTTP_200_OK, r_headers, json.dumps(body)

    # Mock station response for adgs, cadip sessions and cadip files
    for path in "Products", "Sessions", "Files":
        responses.add_callback(
            responses.GET,
            re.compile(f"http://127.0.0.1:.*/{path}.*"),
            callback=mock_station_response,
            content_type=content_type,
        )

    all_requests = []

    def mock_token_request(request):

        # Save the request
        all_requests.append(request)

        # Return a mock token
        token = {
            "access_token": "my_access_token",
            "expires_in": 3600,
            "refresh_token": "my_refresh_token",
            "refresh_expires_in": 7200,
            "token_type": "Bearer",
        }
        return HTTP_200_OK, r_headers, json.dumps(token)

    # Mock token request, without refresh
    responses.add_callback(
        responses.POST,
        re.compile("http://127.0.0.1:.*/oauth2/token"),
        callback=mock_token_request,
        content_type=content_type,
    )

    # Spy on the eodag method that requests a token
    spy_token_request = mocker.spy(TokenAuth, "_token_request")

    # Call the search endpoint from an async function, just like the real search endpoint does
    async def search(collection_id):
        url = f"{os.getenv('router_prefix')}/search?collections={collection_id}"
        response = await run_in_threadpool(client.get, url)
        response.raise_for_status()

    # Call the search endpoint in parallel for each collection
    async def parallel_search():
        async with asyncio.TaskGroup() as tg:
            for collection_id in collection_ids:
                for _ in range(5):  # n parallel calls for each collection
                    tg.create_task(search(collection_id))

        # Assert that the token request method had no error
        assert not spy_token_request.spy_exception
        assert {response.status_code for response in spy_token_request.spy_return_list} == {HTTP_200_OK}

        # Return the list of stations (=providers) for which a token was requested
        token_auths = [call[0][0] for call in spy_token_request.call_args_list]
        token_providers = [auth.provider for auth in token_auths]
        return token_auths, token_providers

    # Check that a token was requested only once per station (=provider)
    token_auths, token_providers = await parallel_search()
    assert sorted(token_providers) == all_providers

    # Assert that the refresh_token was not called
    assert len(all_requests) == len(all_providers)
    for request in all_requests:
        assert "refresh_token" not in request.body
    all_requests.clear()

    # If we call the search again, no token should be requested, because the token is still valid
    spy_token_request.reset_mock()
    _, token_providers = await parallel_search()
    assert not token_providers
    assert not all_requests

    # When the token expires, a refresh token should be requested one for each station
    for token_auth in token_auths:
        token_auth.token_expiration = datetime.datetime(1900, 1, 1)
    spy_token_request.reset_mock()
    _, token_providers = await parallel_search()
    assert sorted(token_providers) == all_providers

    # Assert that the refresh_token was called
    assert len(all_requests) == len(all_providers)
    for request in all_requests:
        assert "refresh_token" in request.body
