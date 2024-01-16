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

EODAG_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config" / "adgs_ws_config.yaml"


def init_adgs_retriever(storage: Any, download_monitor: Any, path: Any):
    """Docstring will be here."""
    try:
        provider = EodagProvider(EODAG_CONFIG, "ADGS")  # default to eodag, default station "ADGS"
    except Exception as exception:
        raise CreateProviderFailed("Failed to setup eodag") from exception
    adgs_storage: Storage = storage
    adgs_monitor: DownloadMonitor = download_monitor
    adgs_working_dir: Path = path
    # End WIP
    return DataRetriever(provider, adgs_storage, adgs_monitor, adgs_working_dir)
