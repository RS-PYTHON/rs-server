"""This will be used to configure dataretriever used for cadip"""

import os
import os.path as osp
from pathlib import Path

from rs_server_common.data_retrieval.eodag_provider import EodagProvider
from rs_server_common.data_retrieval.provider import CreateProviderFailed

DEFAULT_EODAG_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "cadip_ws_config.yaml"


def init_cadip_provider(station: str) -> EodagProvider:
    """Initialize the cadip provider for the given station.

    It initializes an eodag provider for the given station.
    The EODAG configuration file is read from the path given in the EODAG_CADIP_CONFIG var env if set.
    It is read from the path config/cadip_ws_config.yaml otherwise.

    If the station is unknown or if the cadip station configuration reading fails,
    a specific exception is raised to inform the caller of the issue.

    Args:
        station: the station to interact with: ns, mps, mti, nsg, sgs, cadip(?)

    Returns:
        the EodagProvider initialized
    """

    try:
        # Check if the config file path is overriden in the environment variables
        eodag_config = Path(os.environ.get("EODAG_CADIP_CONFIG", DEFAULT_EODAG_CONFIG))
        # default to eodag, stations may be ins, mps, mti, nsg, sgs, cadip(?)
        return EodagProvider(eodag_config, station.lower())
    except Exception as exception:
        raise CreateProviderFailed("Failed to setup eodag") from exception
