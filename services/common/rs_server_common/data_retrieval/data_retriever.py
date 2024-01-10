"""Data retriever module."""
from datetime import datetime
from pathlib import Path

from .download_monitor import DownloadMonitor
from .provider import Product, Provider, TimeRange
from .storage import Storage


class DataRetriever:
    """A data retriever.

    It is responsible to download data with a provider
    and store them on a specific storage.
    It tracks its download activities with a download monitor.
    """

    def __init__(
        self,
        provider: Provider,
        storage: Storage,
        download_monitor: DownloadMonitor,
        working_folder: Path,
    ):
        """Create a data retriever.

        :param provider: the provider used for search and downloads
        :param storage: the storage used for storing downloaded products
        :param download_monitor: the monitor used to track download activities
        :param working_folder: the local working folder for temporary store
        """
        self.provider = provider
        self.storage = storage
        if self.storage:
            self.storage.login()
        self.monitor = download_monitor
        self.work_folder = working_folder
        self.filename = Path("")

    def search(self, start, stop) -> list[Product]:
        """Search for products within the given timerange.

        Search for products using the provider.

        :param within: the timerange criteria
        :return: the products found
        """
        within = TimeRange(datetime.fromisoformat(start), datetime.fromisoformat(stop))
        return self.provider.search(within)

    def download(self, product_id: str, product_name: str) -> None:
        """Download the given product and store it.

        Download the given product in the working folder using the provider.
        Then, stores the product using the storage.
        Keeps track of the download progress using the monitor.

        :param product_id: the id of the product to download
        :param product_name: the name of the uploaded product
        :return: None
        """
        # self.monitor.requested(product_id)
        # self.monitor.started(product_id, datetime.now())
        self.filename = self.work_folder / product_name
        try:
            self.provider.download(product_id, self.filename)
            # self.storage.store(tmp_path, Path(product_name))
            # self.monitor.completed(product_id, datetime.now())
        except Exception as e:
            # self.monitor.failed(product_id, datetime.now(), str(e))
            raise e
        # finally:
        # tmp_path.unlink(missing_ok=True)
