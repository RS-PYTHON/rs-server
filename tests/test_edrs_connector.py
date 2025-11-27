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

"""Pytest tests for the EDRSConnector class."""

from pathlib import Path

import pytest
import yaml

from services.edrs.rs_server_edrs.edrs_connector import (
    EDRSConnector,
    load_station_config,
)

# pylint: disable=redefined-outer-name


@pytest.fixture
def connector(monkeypatch):
    """Provide an EDRSConnector instance with dummy parameters."""
    monkeypatch.setenv("USE_SSL", "FALSE")
    return EDRSConnector(
        host="test_host",
        port=21,
        login="test_user",
        password="dummy_pass",
        ca_cert="ca.pem",
        client_cert="client.crt",
        client_key="client.key",
    )


def test_init_attributes(monkeypatch):
    """Verify attributes set correctly and USE_SSL interpreted."""
    monkeypatch.setenv("USE_SSL", "TRUE")
    conn = EDRSConnector(
        host="h",
        port=21,
        login="login_test",
        password="pass",
        ca_cert="ca",
        client_cert="crt",
        client_key="key",
    )
    assert conn.host == "h"
    assert conn.port == 21
    assert conn.user == "login_test"
    assert conn.password == "pass"
    assert conn.ca_cert == "ca"
    assert conn.use_ssl is True


def test_load_station_config_valid(tmp_path: Path):
    """Test loading valid station config from YAML."""
    config_data = {
        "stations": {
            "stationA": {
                "authentication": {
                    "username": "user",
                    "password": "pass",
                    "ca_crt": "ca.pem",
                    "client_crt": "client.pem",
                    "client_key": "client.key",
                },
                "service": {
                    "url": "example.com",
                    "port": 443,
                },
            },
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = load_station_config(config_path, "stationA")

    assert result == {
        "host": "example.com",
        "port": 443,
        "login": "user",
        "password": "pass",
        "ca_cert": "ca.pem",
        "client_cert": "client.pem",
        "client_key": "client.key",
    }


def test_load_station_config_missing_station(tmp_path: Path):
    """Test error when station not in YAML config."""
    config_data = {"stations": {"stationA": {}}}  # type: ignore
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    with pytest.raises(ValueError, match="Station 'stationB' not found"):
        load_station_config(config_path, "stationB")


def test_load_station_config_missing_fields(tmp_path: Path):
    """Test error when required fields missing."""
    config_data = {
        "stations": {
            "stationA": {
                "authentication": {"username": "user"},
                "service": {"url": "example.com"},
            },
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        load_station_config(config_path, "stationA")

    assert "Missing required fields" in str(excinfo.value)
