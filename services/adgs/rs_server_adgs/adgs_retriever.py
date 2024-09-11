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

"""Docstring will be here."""

import os
import os.path as osp
from pathlib import Path

from rs_server_common.data_retrieval.eodag_provider import EodagProvider
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.settings import env_bool

if env_bool("RSPY_USE_MODULE_FOR_STATION_TOKEN", False):
    DEFAULT_EODAG_CONFIG = (
        Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "adgs_ws_config_token_module.yaml"
    )
else:
    DEFAULT_EODAG_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "adgs_ws_config.yaml"


def init_adgs_provider(station: str) -> EodagProvider:
    """Initialize the adgs provider for the given station.

    It initializes an eodag provider for the given station.
    The EODAG configuration file is read from the path given in the EODAG_ADGS_CONFIG var env if set.
    It is read from the path config/adgs_ws_config.yaml otherwise.

    If the station is unknown or if the adgs station configuration reading fails,
    a specific exception is raised to inform the caller of the issue.

    Args:
        station (str): the station to interact with.

    Returns:
         the EodagProvider initialized

    """
    try:
        # Check if the config file path is overriden in the environment variables
        eodag_config = Path(os.environ.get("EODAG_ADGS_CONFIG", DEFAULT_EODAG_CONFIG))
        return EodagProvider(eodag_config, station.lower())  # default to eodag, default station "adgs"
    except Exception as exception:
        raise CreateProviderFailed("Failed to setup eodag") from exception
