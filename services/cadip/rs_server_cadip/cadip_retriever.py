"""This will be used to configure dataretriever used for cadip"""
import os.path as osp
from pathlib import Path
from typing import Any

from rs_server_common.data_retrieval.data_retriever import DataRetriever
from rs_server_common.data_retrieval.download_monitor import DownloadMonitor
from rs_server_common.data_retrieval.eodag_provider import EodagProvider
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.data_retrieval.storage import Storage
from rs_server_common.utils.provider_ws_address import station_to_server_url

EODAG_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "cadip_ws_config.yaml"


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
