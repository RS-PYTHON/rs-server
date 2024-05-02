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

"""TODO Docstring will be added here"""

import json
import os
import os.path as osp
from pathlib import Path

DEFAULT_STATION_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config" / "stations_cfg.json"


def station_to_server_url(station: str) -> str | None:
    """Retrieve the configuration data (webserver address) for a CADIP station based on its identifier.

    Notes:
        - The station identifier is case-insensitive and is converted to uppercase for matching.
        - The function reads the station configuration data from a JSON file.
        - If the station identifier is not found in the configuration data, the function returns None.

    Args:
        station (str): Identifier for the CADIP station.

    Returns:
        str or None:
            A str containing the webserver address for the specified station,
            or None if the station identifier is not found.



    """

    # Check if the config file path is overriden in the environment variables
    station_config = os.environ.get("RSPY_STATION_CONFIG", DEFAULT_STATION_CONFIG)

    try:
        with open(station_config, encoding="utf-8") as jfile:
            stations_data = json.load(jfile)
            return stations_data.get(station.lower(), None)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        # logger to be added.
        raise ValueError from exc
