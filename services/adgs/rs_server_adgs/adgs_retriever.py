"""Docstring will be here."""
import os
import os.path as osp
from pathlib import Path

from rs_server_common.data_retrieval.eodag_provider import EodagProvider
from rs_server_common.data_retrieval.provider import CreateProviderFailed

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
        return EodagProvider(eodag_config, station)  # default to eodag, default station "ADGS"
    except Exception as exception:
        raise CreateProviderFailed("Failed to setup eodag") from exception
