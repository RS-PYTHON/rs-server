# Copyright 2023-2025 Airbus, CS Group
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

"""EDRS Connector module.

Provides utilities to connect to EDRS stations via FTP/FTPS,
list NOMINAL directories, read remote files (with XML parsing),
and load station connection parameters from YAML configuration.
"""

import os
import os.path as osp
from pathlib import Path
from typing import Any

import xmltodict
import yaml
from rs_server_common.ftp_handler.ftp_handler import FTPClient

# Default path to stations configuration YAML
DEFAULT_EDRS_STATIONS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "edrs_stations.yaml"
EDRS_STATIONS_CONFIG = os.environ.get("EDRS_STATIONS_CONFIG_YAML", DEFAULT_EDRS_STATIONS_CONFIG)


class EDRSConnector(FTPClient):
    """EDRS Connector providing FTP/FTPS access to EDRS stations.

    Inherits from FTPClient for all FTP/FTPS operations, adding:
      - EDRS-specific NOMINAL directory walking
      - Automatic XML parsing for remote files
    """

    def __init__(
        self,
        host: str,
        port: int,
        login: str,
        password: str,
        ca_cert: str,
        client_cert: str,
        client_key: str,
        disable_mlsd: bool = True,
    ):
        """
        Initialize the EDRSConnector.

        Args:
            host: FTP/FTPS server hostname.
            port: Server port number.
            login: Username for authentication.
            password: Password for authentication.
            ca_cert: Path to CA certificate.
            client_cert: Path to client certificate.
            client_key: Path to client key.
            disable_mlsd: Whether to disable MLSD directory listing.
        """
        # Map EDRSConnector arguments to FTPClient
        super().__init__(
            host=host,
            port=port,
            user=login,
            password=password,
            ca_crt=ca_cert,
            client_crt=client_cert,
            client_key=client_key,
            use_ssl=True,
            disable_mlsd=disable_mlsd,
        )

    def walk(self, path: str) -> list[dict[str, Any]]:
        """
        List EDRS NOMINAL directory content.

        Prepends "/NOMINAL/" to the given path and lists all files and directories
        under it using FTPClient's internal methods.

        Args:
            path: Relative NOMINAL path (e.g., "SOME/SUBDIR").

        Returns:
            List of dictionaries with file/directory info: 'path', 'type', 'size'.

        Raises:
            ConnectionError: If not connected to FTP.
        """
        if not self.ftp:
            raise ConnectionError("Not connected. Call connect() first.")

        base_path = f"/NOMINAL/{path.strip('/')}" if "/NOMINAL/" not in path else path
        entries = self._list_directory_entries(base_path)
        current_dir = self.ftp.pwd()
        results = []

        for entry in entries:
            info = self._get_entry_info(entry, current_dir)
            results.append(info)

        return results

    def read_file(self, remote_path: str) -> Any:
        """
        Read a remote file and automatically parse XML if applicable.

        Uses FTPClient.read_file() for retrieval and parses XML content
        into a Python dictionary.

        Args:
            remote_path: Path to remote file.

        Returns:
            Parsed dict for XML files, raw bytes otherwise.

        Raises:
            RuntimeError: If reading or parsing fails.
        """
        raw = super().read_file(remote_path)

        if isinstance(raw, bytes) and remote_path.lower().endswith(".xml"):
            return xmltodict.parse(raw)

        return raw


def load_station_config(config_path: str | Path, station_name: str) -> dict:
    """
    Load connection parameters for a specific station from YAML configuration.

    Supports YAML files where stations can be nested under "stations" key
    or as a YAML string.

    Args:
        config_path: Path to YAML configuration file.
        station_name: Name of the station to retrieve.

    Returns:
        Dictionary with connection parameters suitable for EDRSConnector.

    Raises:
        ValueError: If station not found or required fields are missing.
    """
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Extract stations dictionary, handle YAML-as-string case
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

    connection_params = {
        "host": service.get("url"),
        "port": service.get("port"),
        "login": auth.get("username"),
        "password": auth.get("password"),
        "ca_cert": auth.get("ca_crt"),
        "client_cert": auth.get("client_crt"),
        "client_key": auth.get("client_key"),
    }

    # Validate that all required fields are present
    missing = [k for k, v in connection_params.items() if v is None]
    if missing:
        raise ValueError(f"Missing required fields in config for '{station_name}': {', '.join(missing)}")

    return connection_params
