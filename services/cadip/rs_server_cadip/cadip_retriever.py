"""This will be used to configure dataretriever used for cadip"""
import json
import os.path as osp
from pathlib import Path
from typing import Any

from services.common.rs_server_common.data_retrieval.data_retriever import DataRetriever
from services.common.rs_server_common.data_retrieval.download_monitor import (
    DownloadMonitor,
)
from services.common.rs_server_common.data_retrieval.eodag_provider import EodagProvider
from services.common.rs_server_common.data_retrieval.provider import (
    CreateProviderFailed,
)
from services.common.rs_server_common.data_retrieval.storage import Storage

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
EODAG_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "cadip_ws_config.yaml"


def station_to_server_url(station: str) -> str | None:
    """Retrieve the configuration data (webserver address) for a CADU station based on its identifier.

    Parameters
    ----------
    station : str
        Identifier for the CADU station.

    Returns
    -------
    str or None
        A str containing the webserver address for the specified station,
        or None if the station identifier is not found.

    Example
    -------
    >>> station_to_server_url("station123")
    'https://station123.example.com'

    Notes
    -----
    - The station identifier is case-insensitive and is converted to uppercase for matching.
    - The function reads the station configuration data from a JSON file.
    - If the station identifier is not found in the configuration data, the function returns None.
    """
    try:
        with open(CONF_FOLDER / "stations_cfg.json", encoding="utf-8") as jfile:
            stations_data = json.load(jfile)
            return stations_data.get(station.upper(), None)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        # logger to be added.
        raise ValueError from exc


def init_cadip_data_retriever(
    station: str,
    storage: Any,
    download_monitor: Any,
    path: Any,
):
    """
    Initializes a DataRetriever instance for CADIP data retrieval.

    Parameters:
    - cadip_provider (callable): A callable that creates a CADIP provider instance.
    - station (str): The station identifier for which data retrieval is intended.

    Raises:
    - CreateProviderFailed: If the station does not have a valid server URL.

    Returns:
    DataRetriever: An instance of the DataRetriever class configured with the specified CADIP provider,
    storage, download monitor, and working directory. Note that the storage, download monitor, and working
    directory are currently placeholders (set to None) and will be implemented with download functionality
    in future updates.
    """
    try:
        if not station_to_server_url(station):
            raise CreateProviderFailed("Invalid station")
    except ValueError as exc:
        raise CreateProviderFailed("Invalid station configuration") from exc

    provider = EodagProvider(EODAG_CONFIG, station)  # default to eodag, just init here
    # WIP, will be implemented with download
    cadip_storage: Storage = storage
    cadip_monitor: DownloadMonitor = download_monitor
    cadip_working_dir: Path = path
    # End WIP
    return DataRetriever(provider, cadip_storage, cadip_monitor, cadip_working_dir)
