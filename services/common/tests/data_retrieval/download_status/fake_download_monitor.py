"""Fake implementation for the DownloadMonitor."""
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
        self.history: dict[str, ProductDownload] = {}

    def requested(self, product_id: str):
        """A download has been requested.

        :param product_id:
        :return:
        """
        self.history[product_id] = ProductDownload(product_id, DownloadStatus.NOT_STARTED, None, None, "")

    def started(self, product_id: str, at_time: datetime):
        self.history[product_id].status = DownloadStatus.IN_PROGRESS
        self.history[product_id].start = at_time

    def completed(self, product_id: str, at_time: datetime):
        self.history[product_id].status = DownloadStatus.DONE
        self.history[product_id].end = at_time

    def failed(self, product_id: str, at_time: datetime, with_error: str):
        self.history[product_id].status = DownloadStatus.FAILED
        self.history[product_id].end = at_time
        self.history[product_id].error = with_error
