"""EODAG Provider."""
from dataclasses import dataclass
from pathlib import Path

from eodag import EODataAccessGateway, EOProduct
from services.common.rs_server_common.data_retrieval.provider import (
    CreateProviderFailed,
    Product,
    Provider,
    TimeRange,
)


@dataclass
class EodagConfiguration:
    """Eodag configuration."""

    provider: str
    file: Path


class EodagProvider(Provider):
    """An EODAG provider.

    It uses EODAG to provide data from external sources.
    """

    def __init__(self, config: EodagConfiguration):
        """Create a EODAG provider.

        :param config: the eodag configuration
        """
        self.provider: str = config.provider
        self.client: EODataAccessGateway = self.init_eodag_client(config.file)

    def init_eodag_client(self, config_file: Path):
        """Initialize the eodag client.

        The EODAG client is initialized for the given provider.

        :param config_file: the path to the eodag configuration file
        :return: the initialized eodag client
        """
        try:
            return EODataAccessGateway(config_file.as_posix())
        except Exception as e:
            raise CreateProviderFailed(f"Can't initialize {self.provider} provider") from e

    def _specific_search(self, between: TimeRange) -> dict[str, Product]:
        """TODO To be implemented.

        :param between: the time range
        :return: to be impl
        """
        raise NotImplementedError()

    def download(self, product_id: str, to_file: Path) -> None:
        """Download the expected product at the given local location.

        EODAG needs an EOProduct to download.
        We build an EOProduct from the id and download location
        to be able to call EODAG for download.

        :param product_id: the id of the product to download
        :param to_file: the path where the product has to be download
        :return: None
        """
        product = init_eodag_product(product_id, to_file.name)
        # download_plugin = self.client._plugins_manager.get_download_plugin(product)
        # authent_plugin = self.client._plugins_manager.get_auth_plugin(product.provider)
        # product.register_downloader(download_plugin, authent_plugin)
        self.client.download(product, outputs_prefix=to_file.parent)


def init_eodag_product(file_id: str, download_filename: str) -> EOProduct:
    """Initialize an EO product with minimal properties.

    The title is used by EODAG as the name of the downloaded file.
    The download link is used by EODAG as http request url for download.
    The geometry is mandatory in an EO Product so we add the all earth as geometry.

    :param file_id: the id of EO Product
    :param download_filename: the name of the downloaded file
    :return the initialized EO Product
    """
    return EOProduct(
        "CADIP",
        {
            "id": file_id,
            "title": download_filename,
            "geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))",
            # TODO build from configuration (but how ?)
            "downloadLink": f"http://127.0.0.1:5000/Files({file_id})/$value",
        },
    )
