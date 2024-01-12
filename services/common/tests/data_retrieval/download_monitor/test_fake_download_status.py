"""Unit tests for FakeDownloadMonitor."""
from rs_server_common.data_retrieval.download_monitor import (
    DownloadStatus,
    ProductDownload,
)

from .fake_download_monitor import FakeDownloadMonitor


class TestAFakeDownloadMonitor:
    """Class used to test the functionality of the FakeDownloadMonitor."""

    def test_is_initialized_with_an_empty_history(self):
        """
        Verifies that the FakeDownloadMonitor is initialized with an empty history.

        This test checks if the FakeDownloadMonitor is created with an empty history.

        """
        monitor = FakeDownloadMonitor()
        assert isinstance(monitor.history, dict)
        assert len(monitor.history) == 0

    def test_keeps_track_of_all_status_updates(self, start, end):
        """
        Verifies that the FakeDownloadMonitor keeps track of all status updates.

        This test checks if the FakeDownloadMonitor correctly keeps track of status updates
        for a specific download.

        """
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.started("1", start)
        monitor.completed("1", end)

        download_history = monitor.history["1"]
        assert download_history[0].status == DownloadStatus.NOT_STARTED
        assert download_history[1].status == DownloadStatus.IN_PROGRESS
        assert download_history[2].status == DownloadStatus.DONE
        assert len(download_history) == 3


class TestADownloadHasBeenRequested:
    """Class used to test the functionality related to a new download request in the FakeDownloadMonitor."""

    def __init__(self):
        pass

    def test_a_new_download_is_created(self):
        """
        Verifies that a new download is created when a download request is made.

        This test checks if a new download is created in the FakeDownloadMonitor when a download request is made.

        """
        monitor = FakeDownloadMonitor()

        monitor.requested("1")

        assert monitor.download_state("1") == ProductDownload("1", DownloadStatus.NOT_STARTED, None, None, "")

    def test_a_new_download_is_not_created(self):
        """
        Verifies that a new download is created when a download request is made.

        This test checks if a new download is created in the FakeDownloadMonitor when a download request is made.

        """
        monitor = FakeDownloadMonitor()

        monitor.requested("1")

        assert monitor.download_state("1") != ProductDownload("1", DownloadStatus.DONE, None, None, "")


class TestADownloadHasBeenStarted:
    """Class used to test the functionality related to a download being started in the FakeDownloadMonitor."""

    def test_the_status_is_updated_to_in_progress(self, start):
        """
        Verifies that the status is updated to 'IN_PROGRESS' when a download has been started.

        This test checks if the status of the download is correctly updated to 'IN_PROGRESS' when the
        download has been started.

        """
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")

        monitor.started("1", start)

        assert monitor.download_state("1").status == DownloadStatus.IN_PROGRESS

    def test_the_start_time_is_setup(self, start):
        """
        Verifies that the start time is correctly set when a download has been started.

        This test checks if the start time of the download is correctly set when the download has been started.

        """
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")

        monitor.started("1", start)

        assert monitor.download_state("1").start == start


class TestADownloadHasBeenCompleted:
    """Class used to test the functionality related to a download being completed in the FakeDownloadMonitor."""

    def test_the_status_is_updated_to_done(self, start, end):
        """
        Verifies that the status is updated to 'DONE' when a download has been completed.

        This test checks if the status of the download is correctly updated to 'DONE' when the
        download has been completed.

        """
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")
        monitor.started("1", start)

        monitor.completed("1", end)

        assert monitor.download_state("1").status == DownloadStatus.DONE

    def test_the_end_time_is_setup(self, start, end):
        """
        Verifies that the end time is correctly set when a download has been completed.

        This test checks if the end time of the download is correctly set when the download has been completed.

        """
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")
        monitor.started("1", start)

        monitor.completed("1", end)

        assert monitor.download_state("1").end == end


class TestADownloadHasFailed:
    """Class used to test the functionality related to a download failure in the FakeDownloadMonitor."""

    def test_the_status_is_updated_to_failed(self, start, end):
        """
        Verifies that the status is updated to 'FAILED' when a download fails.

        This test checks if the status of a download is correctly updated to 'FAILED'
        when a failure occurs during the download process.

        """
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")
        monitor.started("1", start)

        monitor.failed("1", end, "An error has occurred.")

        assert monitor.download_state("1").status == DownloadStatus.FAILED

    def test_the_error_message_is_setup(self, start, end):
        """
        Verifies that the error message is correctly set when a download fails.

        This test checks if the error message is properly set in the download state
        when a download encounters a failure.

        """
        monitor = FakeDownloadMonitor()
        monitor.requested("1")
        monitor.requested("2")
        monitor.started("1", start)

        monitor.failed("1", end, "An error has occurred.")

        assert monitor.download_state("1").error == "An error has occurred."
