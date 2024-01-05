from datetime import datetime, timedelta
from pathlib import Path

import pytest
from rs_server_common.data_retrieval.data_retriever import DataRetriever
from rs_server_common.data_retrieval.download_monitor import DownloadStatus
from rs_server_common.data_retrieval.provider import DownloadProductFailed, Product

from tests.data_retrieval.download_monitor.fake_download_monitor import (
    FakeDownloadMonitor,
)
from tests.data_retrieval.provider.fake_provider import FakeProvider
from tests.data_retrieval.storage.fake_storage import FakeStorage, NotLogged

# TODO factory to create the "true" DataRetriever (context manager ?)


@pytest.fixture
def a_product() -> Product:
    return Product(
        "1",
        {
            "id": "1",
            "name": "file_1",
            "other": "value_1",
        },
    )


@pytest.fixture
def a_provider(a_product) -> FakeProvider:
    return FakeProvider([a_product])


@pytest.fixture
def a_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
def a_monitor() -> FakeDownloadMonitor:
    return FakeDownloadMonitor()


@pytest.fixture
def a_working_folder(tmp_path) -> Path:
    return tmp_path


@pytest.fixture
def not_found_folder(tmp_path) -> Path:
    return tmp_path / "not_found"


class TestADataRetriever:
    def test_is_init_with_a_specific_provider(self, a_provider, a_storage, a_monitor, a_working_folder):
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert retriever.provider is a_provider

    def test_is_init_with_a_specific_storage(self, a_provider, a_storage, a_monitor, a_working_folder):
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert retriever.storage is a_storage

    def test_is_init_with_a_specific_download_monitor(self, a_provider, a_storage, a_monitor, a_working_folder):
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert retriever.monitor is a_monitor

    def test_is_init_with_a_working_folder(self, a_provider, a_storage, a_monitor, a_working_folder):
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert retriever.work_folder is a_working_folder

    def test_login_on_storage_at_creation(self, a_provider, a_storage, a_monitor, a_working_folder):
        DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        assert a_storage.logged


class TestADataRetrieverDownload:
    def test_notifies_the_monitor_with_the_request_first(self, a_provider, a_storage, a_monitor, a_working_folder):
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
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")

        # The second status is the download start
        download_started = a_monitor.history["1"][1]
        assert download_started.status == DownloadStatus.IN_PROGRESS
        assert timedelta(0) <= datetime.now() - download_started.start <= timedelta(seconds=1)

        # TODO it would be cool to assert the notification is made before launching the download

    def test_uses_the_provider_to_download_the_file(self, a_provider, a_storage, a_monitor, a_working_folder):
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
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")

        # The last status is the download completion
        download_done = a_monitor.download_state("1")
        assert download_done.status == DownloadStatus.DONE
        assert timedelta(0) <= datetime.now() - download_done.end <= timedelta(seconds=1)

    def test_removes_the_temporary_file_of_the_working_folder(self, a_provider, a_storage, a_monitor, a_working_folder):
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        retriever.download("1", "downloaded.txt")
        assert not (a_working_folder / "downloaded.txt").exists()


class TestADataRetrieverDownloadFailure:
    @pytest.mark.xfail
    def test_what_happens_if_the_download_status_update_fails(self, a_provider, a_storage, a_monitor, a_working_folder):
        # TODO To be defined
        assert False

    def test_fails_if_download_fails(self, a_provider, a_storage, a_monitor, a_working_folder):
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        with pytest.raises(DownloadProductFailed):
            retriever.download("not found product", "downloaded.txt")
        assert a_storage.last_upload is None

    def test_notifies_monitor_with_the_download_failure(self, a_provider, a_storage, a_monitor, a_working_folder):
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)

        with pytest.raises(DownloadProductFailed):
            retriever.download("not found product", "downloaded.txt")

        download_failed = a_monitor.download_state("not found product")
        assert download_failed.status == DownloadStatus.FAILED
        assert timedelta(0) <= datetime.now() - download_failed.end <= timedelta(seconds=1)
        assert download_failed.error == "Product with id 'not found product' doesn't exist."

    def test_fails_if_store_fails(self, a_provider, a_storage, a_monitor, a_working_folder):
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        # This enables the storage to raise an exception when storing the file
        a_storage.logout()

        with pytest.raises(NotLogged):
            retriever.download("1", "downloaded.txt")

    def test_notifies_monitor_with_the_storing_failure(self, a_provider, a_storage, a_monitor, a_working_folder):
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
        retriever = DataRetriever(a_provider, a_storage, a_monitor, a_working_folder)
        # This enables the storage to raise an exception when storing the file
        a_storage.logout()

        with pytest.raises(NotLogged):
            retriever.download("1", "downloaded.txt")

        assert not (a_working_folder / "downloaded.txt").exists()
