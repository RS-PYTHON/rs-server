"""Unit tests for FakeDownloadMonitor."""
from rs_server_common.data_retrieval.download_monitor import (
    DownloadStatus,
    ProductDownload,
)

from tests.data_retrieval.download_status.fake_download_monitor import (
    FakeDownloadMonitor,
)


class TestAFakeDownloadMonitor:
    def test_is_initialized_with_an_empty_history(self):
        monitor = FakeDownloadMonitor()
        assert isinstance(monitor.history, dict)
        assert len(monitor.history) == 0


class TestADownloadHasBeenRequested:
    def test_a_new_download_is_created(self):
        monitor = FakeDownloadMonitor()

        monitor.requested("1")

        assert monitor.history["1"] == ProductDownload("1", DownloadStatus.NOT_STARTED, None, None, "")


class TestADownloadHasBeenStarted:
    def test_the_status_is_updated_to_in_progress(self, start):
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")

        monitor.started("1", start)

        assert monitor.history["1"].status == DownloadStatus.IN_PROGRESS

    def test_the_start_time_is_setup(self, start):
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")

        monitor.started("1", start)

        assert monitor.history["1"].start == start


class TestADownloadHasBeenCompleted:
    def test_the_status_is_updated_to_done(self, start, end):
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")
        monitor.started("1", start)

        monitor.completed("1", end)

        assert monitor.history["1"].status == DownloadStatus.DONE

    def test_the_end_time_is_setup(self, start, end):
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")
        monitor.started("1", start)

        monitor.completed("1", end)

        assert monitor.history["1"].end == end


class TestADownloadHasFailed:
    def test_the_status_is_updated_to_failed(self, start, end):
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")
        monitor.started("1", start)

        monitor.failed("1", end, "An error has occurred.")

        assert monitor.history["1"].status == DownloadStatus.FAILED

    def test_the_error_message_is_setup(self, start, end):
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")
        monitor.started("1", start)

        monitor.failed("1", end, "An error has occurred.")

        assert monitor.history["1"].error == "An error has occurred."
