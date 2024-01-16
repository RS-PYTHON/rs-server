"""Docstring will be here."""
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
EODAG_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "adgs_ws_config.yaml"


def init_adgs_retriever(storage: Any, download_monitor: Any, path: Any):
    """Docstring will be here."""
    try:
        provider = EodagProvider(EODAG_CONFIG, "ADGS")  # default to eodag, default station "ADGS"
    except Exception as exception:
        raise CreateProviderFailed("Failed to setup eodag") from exception
    cadip_storage: Storage = storage
    cadip_monitor: DownloadMonitor = download_monitor
    cadip_working_dir: Path = path
    # End WIP
    return DataRetriever(provider, cadip_storage, cadip_monitor, cadip_working_dir)
