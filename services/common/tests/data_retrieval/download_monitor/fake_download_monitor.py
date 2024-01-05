"""Fake implementation for the DownloadMonitor."""
import copy
from collections import defaultdict
from datetime import datetime

from rs_server_common.data_retrieval.download_monitor import (
    DownloadMonitor,
    DownloadStatus,
    ProductDownload,
)


class FakeDownloadMonitor(DownloadMonitor):
    """Fake implementation for the DownloadMonitor."""

    def __init__(self):
        """Create a FakeDownloadMonitor.

        The monitor is initially empty.
        """
        self.history: dict[str, list[ProductDownload]] = defaultdict(list)

    def requested(self, product_id: str):
        """A download has been requested.

        :param product_id: id of the product to download
        :return: None
        """
        download = ProductDownload(product_id, DownloadStatus.NOT_STARTED, None, None, "")
        self._status_update(download)

    def started(self, product_id: str, at_time: datetime):
        """A download has been started.

        :param product_id: id of the product to download
        :param at_time: start time of the download
        :return: None
        """
        download = copy.deepcopy(self.download_state(product_id))
        download.status = DownloadStatus.IN_PROGRESS
        download.start = at_time
        self._status_update(download)

    def completed(self, product_id: str, at_time: datetime):
        """A download has been completed.

        :param product_id: id of the downloaded product
        :param at_time: end time of the download
        :return: None
        """
        download = copy.deepcopy(self.download_state(product_id))
        download.status = DownloadStatus.DONE
        download.end = at_time
        self._status_update(download)

    def failed(self, product_id: str, at_time: datetime, with_error: str):
        """A download has failed.

        :param product_id: id of the downloaded product
        :param at_time: end time of the download
        :param with_error: message of the error
        :return: None
        """
        download = copy.deepcopy(self.download_state(product_id))
        download.status = DownloadStatus.FAILED
        download.end = at_time
        download.error = with_error
        self._status_update(download)

    def _status_update(self, download: ProductDownload) -> None:
        """Add the status update to the history.

        :param download: the new download status
        :return: None
        """
        self.history[download.id_].append(download)

    def download_state(self, product_id: str) -> ProductDownload:
        """Retrieve the current download state in the history.

        :param product_id: the id of the downloaded product
        :return: the download status
        """
        return self.history[product_id][-1]
