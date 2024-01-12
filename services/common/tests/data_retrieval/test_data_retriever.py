"""This module is used to tests data retriever."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from rs_server_common.data_retrieval.data_retriever import DataRetriever
from rs_server_common.data_retrieval.download_monitor import DownloadStatus
from rs_server_common.data_retrieval.provider import DownloadProductFailed, Product

from .download_monitor.fake_download_monitor import FakeDownloadMonitor
from .provider.fake_provider import FakeProvider
from .storage.fake_storage import FakeStorage, NotLogged


@pytest.fixture(name="a_product")
def product_fixture() -> Product:
    """Fixture providing a sample Product instance."""
    return Product(
        "1",
        {
            "id": "1",
            "name": "file_1",
            "other": "value_1",
        },
    )


@pytest.fixture(name="a_provider")
def a_provider_fixture(a_product) -> FakeProvider:
    """Fixture providing a FakeProvider instance for testing."""
    return FakeProvider([a_product])


@pytest.fixture(name="a_storage")
def a_storage_fixture() -> FakeStorage:
    """Fixture providing a FakeStorage instance for testing."""
    return FakeStorage()


@pytest.fixture(name="a_monitor")
def a_monitor_fixture() -> FakeDownloadMonitor:
    """Fixture providing a FakeDownloadMonitor instance for testing."""
    return FakeDownloadMonitor()


@pytest.fixture(name="a_working_folder")
def a_working_folder_fixture(tmp_path) -> Path:
    """Fixture providing a temporary working folder path for testing."""
    return tmp_path


@pytest.fixture(name="not_found_folder")
def not_found_folder_fixture(tmp_path) -> Path:
    """Fixture providing a temporary folder for testing scenarios where files are not found."""
    return tmp_path / "not_found"


class TestADataRetriever:
    """Class used to test a data retriever."""

    def test_is_init_with_a_specific_provider(self, a_provider, a_storage, a_monitor, a_working_folder):
        """Verifies that the DataRetriever is initialized with the specified provider."""
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert retriever.provider is a_provider

    def test_is_init_with_a_specific_storage(self, a_provider, a_storage, a_monitor, a_working_folder):
        """Verifies that the DataRetriever is initialized with the specified storage."""
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert retriever.storage is a_storage

    def test_is_init_with_a_specific_download_monitor(self, a_provider, a_storage, a_monitor, a_working_folder):
        """Verifies that the DataRetriever is initialized with the specified download monitor."""
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert retriever.monitor is a_monitor

    def test_is_init_with_a_working_folder(self, a_provider, a_storage, a_monitor, a_working_folder):
        """Verifies that the DataRetriever is initialized with the specified working folder."""
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert retriever.work_folder is a_working_folder

    def test_login_on_storage_at_creation(self, a_provider, a_storage, a_monitor, a_working_folder):
        """Verifies that the storage is logged in during DataRetriever creation."""
        DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert a_storage.logged


class TestADataRetrieverDownload:
    """Class used to test a data retriever download process."""

    def test_notifies_the_monitor_with_the_request_first(self, a_provider, a_storage, a_monitor, a_working_folder):
        """
        Verifies that the monitor is notified with the download request first.

        This test initializes a DataRetriever, triggers a download, and checks if the
        monitor is notified with the download request as the first status.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")

        # The first status is the download request
        download_requested = a_monitor.history["1"][0]
        assert download_requested.status == DownloadStatus.NOT_STARTED

    def test_notifies_the_monitor_with_the_start_just_before_downloading(
        self,
        a_provider,
        a_storage,
        a_monitor,
        a_working_folder,
    ):
        """
        Verifies that the monitor is notified with the download start just before downloading.

        This test initializes a DataRetriever, triggers a download, and checks if the
        monitor is notified with the download start just before the actual download begins.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")

        # The second status is the download start
        download_started = a_monitor.history["1"][1]
        assert download_started.status == DownloadStatus.IN_PROGRESS
        assert timedelta(0) <= datetime.now() - download_started.start <= timedelta(seconds=1)

        # TODO it would be cool to assert the notification is made before launching the download

    def test_uses_the_provider_to_download_the_file(self, a_provider, a_storage, a_monitor, a_working_folder):
        """
        Verifies that the DataRetriever uses the provider to download the file.

        This test initializes a DataRetriever, triggers a download, and checks if the
        provider is used to download the specified file.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")

        assert a_provider.last_download.product_id == "1"
        assert a_provider.last_download.location == a_working_folder / "downloaded.txt"

    def test_uploads_the_file_to_the_storage_once_the_file_is_downloaded(
        self,
        a_provider,
        a_storage,
        a_monitor,
        a_working_folder,
    ):
        """
        Verifies that the DataRetriever uploads the file to the storage after downloading.

        This test initializes a DataRetriever, triggers a download, and checks if the
        file is uploaded to the storage after the download is finished.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")

        # The upload has been made after the download is finished
        # otherwise the storage would raise an exception.
        assert a_storage.last_upload.uploaded_file == a_working_folder / "downloaded.txt"
        assert a_storage.last_upload.location == Path("downloaded.txt")

    def test_notifies_the_monitor_with_the_completion_once_the_file_is_uploaded(
        self,
        a_provider,
        a_storage,
        a_monitor,
        a_working_folder,
    ):
        """
        Verifies that the monitor is notified with the download completion once the file is uploaded.

        This test initializes a DataRetriever, triggers a download, and checks if the
        monitor is notified with the download completion once the file is uploaded.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")

        # The last status is the download completion
        download_done = a_monitor.download_state("1")
        assert download_done.status == DownloadStatus.DONE
        assert timedelta(0) <= datetime.now() - download_done.end <= timedelta(seconds=1)

    def test_removes_the_temporary_file_of_the_working_folder(self, a_provider, a_storage, a_monitor, a_working_folder):
        """
        Verifies that the temporary file in the working folder is removed after download.

        This test initializes a DataRetriever, triggers a download, and checks if the
        temporary file in the working folder is removed after the download is finished.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")
        assert not (a_working_folder / "downloaded.txt").exists()


class TestADataRetrieverDownloadFailure:
    """Class used to test a failure in data retrieval download process."""

    # pylint: disable=unused-argument
    @pytest.mark.xfail
    def test_what_happens_if_the_download_status_update_fails(self, a_provider, a_storage, a_monitor, a_working_folder):
        """
        Tests the behavior when the download status update fails.

        This test should define the behavior and assert the expected outcomes when there's
        a failure in updating the download status. It is currently marked as expected to fail (xfail).

        """
        # TODO To be defined
        assert False

    def test_fails_if_download_fails(self, a_provider, a_storage, a_monitor, a_working_folder):
        """
        Ensures that the process fails if the download fails.

        This test checks that a `DownloadProductFailed` exception is raised when trying
        to download a non-existent product, and that no upload occurs in such a case.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        with pytest.raises(DownloadProductFailed):
            retriever.download("not found product", "downloaded.txt")
        assert a_storage.last_upload is None

    def test_notifies_monitor_with_the_download_failure(self, a_provider, a_storage, a_monitor, a_working_folder):
        """
        Verifies that the monitor is notified of the download failure.

        This test ensures that the monitor is updated with the download failure status
        when an attempt to download a non-existent product is made, including the appropriate error message.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)

        with pytest.raises(DownloadProductFailed):
            retriever.download("not found product", "downloaded.txt")

        download_failed = a_monitor.download_state("not found product")
        assert download_failed.status == DownloadStatus.FAILED
        assert timedelta(0) <= datetime.now() - download_failed.end <= timedelta(seconds=1)
        assert download_failed.error == "Product with id 'not found product' doesn't exist."

    def test_fails_if_store_fails(self, a_provider, a_storage, a_monitor, a_working_folder):
        """
        Ensures the process fails if storing the downloaded file fails.

        This test checks that a `NotLogged` exception is raised if the storage system
        fails to store the downloaded file, simulating a scenario where the storage system
        is not properly logged in.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        # This enables the storage to raise an exception when storing the file
        a_storage.logout()

        with pytest.raises(NotLogged):
            retriever.download("1", "downloaded.txt")

    def test_notifies_monitor_with_the_storing_failure(self, a_provider, a_storage, a_monitor, a_working_folder):
        """
        Verifies that the monitor is notified of the storing failure.

        This test ensures that the monitor is updated with the download failure status
        when there is a failure in storing the downloaded file, including the appropriate error message.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        # This enables the storage to raise an exception when storing the file
        a_storage.logout()

        with pytest.raises(NotLogged):
            retriever.download("1", "downloaded.txt")

        download_failed = a_monitor.download_state("1")
        assert download_failed.status == DownloadStatus.FAILED
        assert timedelta(0) <= datetime.now() - download_failed.end <= timedelta(seconds=1)
        assert download_failed.error == "Not logged."

    def test_removes_the_temporary_file_of_the_working_folder_even_if_download_failed(
        self,
        a_provider,
        a_storage,
        a_monitor,
        a_working_folder,
    ):
        """
        Verifies that the temporary file is removed from the working folder even if the download fails.

        This test checks that, in the event of a download failure, the temporary file in
        the working folder is still removed, ensuring no residue is left from the failed process.

        """
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        # This enables the storage to raise an exception when storing the file
        a_storage.logout()

        with pytest.raises(NotLogged):
            retriever.download("1", "downloaded.txt")

        assert not (a_working_folder / "downloaded.txt").exists()
