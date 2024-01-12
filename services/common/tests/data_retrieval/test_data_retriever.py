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


@pytest.fixture
def _product() -> Product:
    """Fixture providing a sample Product instance."""
    return Product(
        "1",
        {
            "id": "1",
            "name": "file_1",
            "other": "value_1",
        },
    )


@pytest.fixture
def _provider(_product) -> FakeProvider:
    """Fixture providing a FakeProvider instance for testing."""
    return FakeProvider([_product])


@pytest.fixture
def _storage() -> FakeStorage:
    """Fixture providing a FakeStorage instance for testing."""
    return FakeStorage()


@pytest.fixture
def _monitor() -> FakeDownloadMonitor:
    """Fixture providing a FakeDownloadMonitor instance for testing."""
    return FakeDownloadMonitor()


@pytest.fixture
def _working_folder(tmp_path) -> Path:
    """Fixture providing a temporary working folder path for testing."""
    return tmp_path


@pytest.fixture
def not_found_folder(tmp_path) -> Path:
    """Fixture providing a temporary folder for testing scenarios where files are not found."""
    return tmp_path / "not_found"


class TestADataRetriever:
    """Class used to test a data retriever."""

    def test_is_init_with_a_specific_provider(self, _provider, _storage, _monitor, _working_folder):
        """Verifies that the DataRetriever is initialized with the specified provider."""
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        assert retriever.provider is _provider

    def test_is_init_with_a_specific_storage(self, _provider, _storage, _monitor, _working_folder):
        """Verifies that the DataRetriever is initialized with the specified storage."""
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        assert retriever.storage is _storage

    def test_is_init_with_a_specific_download_monitor(self, _provider, _storage, _monitor, _working_folder):
        """Verifies that the DataRetriever is initialized with the specified download monitor."""
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        assert retriever.monitor is _monitor

    def test_is_init_with_a_working_folder(self, _provider, _storage, _monitor, _working_folder):
        """Verifies that the DataRetriever is initialized with the specified working folder."""
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        assert retriever.work_folder is _working_folder

    def test_login_on_storage_at_creation(self, _provider, _storage, _monitor, _working_folder):
        """Verifies that the storage is logged in during DataRetriever creation."""
        DataRetriever(_provider, _storage, _monitor, _working_folder)
        assert _storage.logged


class TestADataRetrieverDownload:
    """Class used to test a data retriever download process."""

    def test_notifies_the_monitor_with_the_request_first(self, _provider, _storage, _monitor, _working_folder):
        """
        Verifies that the monitor is notified with the download request first.

        This test initializes a DataRetriever, triggers a download, and checks if the
        monitor is notified with the download request as the first status.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        retriever.download("1", "downloaded.txt")

        # The first status is the download request
        download_requested = _monitor.history["1"][0]
        assert download_requested.status == DownloadStatus.NOT_STARTED

    def test_notifies_the_monitor_with_the_start_just_before_downloading(
        self,
        _provider,
        _storage,
        _monitor,
        _working_folder,
    ):
        """
        Verifies that the monitor is notified with the download start just before downloading.

        This test initializes a DataRetriever, triggers a download, and checks if the
        monitor is notified with the download start just before the actual download begins.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        retriever.download("1", "downloaded.txt")

        # The second status is the download start
        download_started = _monitor.history["1"][1]
        assert download_started.status == DownloadStatus.IN_PROGRESS
        assert timedelta(0) <= datetime.now() - download_started.start <= timedelta(seconds=1)

        # TODO it would be cool to assert the notification is made before launching the download

    def test_uses_the_provider_to_download_the_file(self, _provider, _storage, _monitor, _working_folder):
        """
        Verifies that the DataRetriever uses the provider to download the file.

        This test initializes a DataRetriever, triggers a download, and checks if the
        provider is used to download the specified file.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        retriever.download("1", "downloaded.txt")

        assert _provider.last_download.product_id == "1"
        assert _provider.last_download.location == _working_folder / "downloaded.txt"

    def test_uploads_the_file_to_the_storage_once_the_file_is_downloaded(
        self,
        _provider,
        _storage,
        _monitor,
        _working_folder,
    ):
        """
        Verifies that the DataRetriever uploads the file to the storage after downloading.

        This test initializes a DataRetriever, triggers a download, and checks if the
        file is uploaded to the storage after the download is finished.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        retriever.download("1", "downloaded.txt")

        # The upload has been made after the download is finished
        # otherwise the storage would raise an exception.
        assert _storage.last_upload.uploaded_file == _working_folder / "downloaded.txt"
        assert _storage.last_upload.location == Path("downloaded.txt")

    def test_notifies_the_monitor_with_the_completion_once_the_file_is_uploaded(
        self,
        _provider,
        _storage,
        _monitor,
        _working_folder,
    ):
        """
        Verifies that the monitor is notified with the download completion once the file is uploaded.

        This test initializes a DataRetriever, triggers a download, and checks if the
        monitor is notified with the download completion once the file is uploaded.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        retriever.download("1", "downloaded.txt")

        # The last status is the download completion
        download_done = _monitor.download_state("1")
        assert download_done.status == DownloadStatus.DONE
        assert timedelta(0) <= datetime.now() - download_done.end <= timedelta(seconds=1)

    def test_removes_the_temporary_file_of_the_working_folder(self, _provider, _storage, _monitor, _working_folder):
        """
        Verifies that the temporary file in the working folder is removed after download.

        This test initializes a DataRetriever, triggers a download, and checks if the
        temporary file in the working folder is removed after the download is finished.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        retriever.download("1", "downloaded.txt")
        assert not (_working_folder / "downloaded.txt").exists()


class TestADataRetrieverDownloadFailure:
    """Class used to test a failure in data retrieval download process."""

    @pytest.mark.xfail
    def test_what_happens_if_the_download_status_update_fails(self, _provider, _storage, _monitor, _working_folder):
        """
        Tests the behavior when the download status update fails.

        This test should define the behavior and assert the expected outcomes when there's
        a failure in updating the download status. It is currently marked as expected to fail (xfail).

        """
        # TODO To be defined
        assert False

    def test_fails_if_download_fails(self, _provider, _storage, _monitor, _working_folder):
        """
        Ensures that the process fails if the download fails.

        This test checks that a `DownloadProductFailed` exception is raised when trying
        to download a non-existent product, and that no upload occurs in such a case.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        with pytest.raises(DownloadProductFailed):
            retriever.download("not found product", "downloaded.txt")
        assert _storage.last_upload is None

    def test_notifies_monitor_with_the_download_failure(self, _provider, _storage, _monitor, _working_folder):
        """
        Verifies that the monitor is notified of the download failure.

        This test ensures that the monitor is updated with the download failure status
        when an attempt to download a non-existent product is made, including the appropriate error message.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)

        with pytest.raises(DownloadProductFailed):
            retriever.download("not found product", "downloaded.txt")

        download_failed = _monitor.download_state("not found product")
        assert download_failed.status == DownloadStatus.FAILED
        assert timedelta(0) <= datetime.now() - download_failed.end <= timedelta(seconds=1)
        assert download_failed.error == "Product with id 'not found product' doesn't exist."

    def test_fails_if_store_fails(self, _provider, _storage, _monitor, _working_folder):
        """
        Ensures the process fails if storing the downloaded file fails.

        This test checks that a `NotLogged` exception is raised if the storage system
        fails to store the downloaded file, simulating a scenario where the storage system
        is not properly logged in.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        # This enables the storage to raise an exception when storing the file
        _storage.logout()

        with pytest.raises(NotLogged):
            retriever.download("1", "downloaded.txt")

    def test_notifies_monitor_with_the_storing_failure(self, _provider, _storage, _monitor, _working_folder):
        """
        Verifies that the monitor is notified of the storing failure.

        This test ensures that the monitor is updated with the download failure status
        when there is a failure in storing the downloaded file, including the appropriate error message.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        # This enables the storage to raise an exception when storing the file
        _storage.logout()

        with pytest.raises(NotLogged):
            retriever.download("1", "downloaded.txt")

        download_failed = _monitor.download_state("1")
        assert download_failed.status == DownloadStatus.FAILED
        assert timedelta(0) <= datetime.now() - download_failed.end <= timedelta(seconds=1)
        assert download_failed.error == "Not logged."

    def test_removes_the_temporary_file_of_the_working_folder_even_if_download_failed(
        self,
        _provider,
        _storage,
        _monitor,
        _working_folder,
    ):
        """
        Verifies that the temporary file is removed from the working folder even if the download fails.

        This test checks that, in the event of a download failure, the temporary file in
        the working folder is still removed, ensuring no residue is left from the failed process.

        """
        retriever = DataRetriever(_provider, _storage, _monitor, _working_folder)
        # This enables the storage to raise an exception when storing the file
        _storage.logout()

        with pytest.raises(NotLogged):
            retriever.download("1", "downloaded.txt")

        assert not (_working_folder / "downloaded.txt").exists()
