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

"""Module used to connect to EDRS stations using EDRSConnector."""
import os
import os.path as osp
from pathlib import Path

import yaml
from rs_server_edrs.edrs_connector import EDRSConnector

DEFAULT_EDRS_STATIONS_CONFIG = ADGS_CONFIG = (
    Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "edrs_stations.yaml"
)
EDRS_STATIONS_CONFIG = os.environ.get("EDRS_STATIONS_CONFIG_YAML", DEFAULT_EDRS_STATIONS_CONFIG)


def load_station_config(config_path: str | Path, station_name: str) -> dict:
    """Load connection parameters for a specific station from YAML config."""
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Handle case where stations are provided as a YAML string under one key
    stations_data = config.get("stations")
    if isinstance(stations_data, str):
        stations = yaml.safe_load(stations_data)
    else:
        stations = stations_data

    if not stations or station_name not in stations:
        raise ValueError(f"Station '{station_name}' not found in configuration file: {config_path}")

    station = stations[station_name]
    auth = station.get("authentication", {})
    service = station.get("service", {})
    # Map configuration to EDRSConnector expected args
    connection_params = {
        "host": service.get("url"),
        "port": service.get("port"),
        "login": auth.get("username"),
        "password": auth.get("password"),
        "ca_cert": auth.get("ca_crt"),
        "client_cert": auth.get("client_crt"),
        "client_key": auth.get("client_key"),
    }

    # Validate required fields
    missing = [k for k, v in connection_params.items() if v is None]
    if missing:
        raise ValueError(f"Missing required fields in config for '{station_name}': {', '.join(missing)}")
    return connection_params


if __name__ == "__main__":
    STATION_NAME = "bedc"
    client = EDRSConnector(**load_station_config(EDRS_STATIONS_CONFIG, STATION_NAME))

    client.connect()

    client.close()
