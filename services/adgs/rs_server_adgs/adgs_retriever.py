"""Docstring will be here."""
import os
import os.path as osp
from pathlib import Path
from typing import Any

from rs_server_common.data_retrieval.data_retriever import DataRetriever
from rs_server_common.data_retrieval.download_monitor import DownloadMonitor
from rs_server_common.data_retrieval.eodag_provider import EodagProvider
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.data_retrieval.storage import Storage

DEFAULT_EODAG_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "adgs_ws_config.yaml"


def init_adgs_retriever(station: str, storage: Any, download_monitor: Any, path: Any):
    """Docstring will be here."""

    # Check if the config file path is overriden in the environment variables
    eodag_config = Path(os.environ.get("EODAG_ADGS_CONFIG", DEFAULT_EODAG_CONFIG))

    try:
        provider = EodagProvider(eodag_config, station)  # default to eodag, default station "ADGS"
    except Exception as exception:
        raise CreateProviderFailed("Failed to setup eodag") from exception
    adgs_storage: Storage = storage
    adgs_monitor: DownloadMonitor = download_monitor
    adgs_working_dir: Path = path
    # End WIP
    return DataRetriever(provider, adgs_storage, adgs_monitor, adgs_working_dir)
