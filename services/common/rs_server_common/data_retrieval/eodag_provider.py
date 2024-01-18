"""EODAG Provider."""
import os
from pathlib import Path

from eodag import EODataAccessGateway, EOProduct

from .provider import CreateProviderFailed, Provider, TimeRange


class EodagProvider(Provider):
    """An EODAG provider.

    It uses EODAG to provide data from external sources.
    """

    def __init__(self, config_file: Path, provider: str):
        """Create a EODAG provider.

        :param config: the eodag configuration
        """
        self.provider: str = provider
        self.client: EODataAccessGateway = self.init_eodag_client(config_file)
        self.client.set_preferred_provider(self.provider)

    def init_eodag_client(self, config_file: Path) -> EODataAccessGateway:
        """Initialize the eodag client.

        The EODAG client is initialized for the given provider.

        :param config_file: the path to the eodag configuration file
        :return: the initialized eodag client
        """
        try:
            return EODataAccessGateway(config_file.as_posix())
        except Exception as e:
            raise CreateProviderFailed(f"Can't initialize {self.provider} provider") from e

    def _specific_search(self, between: TimeRange) -> list[EOProduct]:
        """
        Conducts a search for products within a specified time range.

        This private method interfaces with the client's search functionality,
        retrieving products that fall within the given time range. The 'between'
        parameter is expected to be a TimeRange object, encompassing start and end
        timestamps. The method returns a dictionary of products keyed by their
        respective identifiers.

        Args:
            between (TimeRange): An object representing the start and end timestamps
                                for the search range.

        Returns:
            dict[str, EOProduct]: A dictionary where keys are product identifiers and
                                values are EOProduct instances.

        Note:
            The time format of the 'between' parameter should be verified or formatted
            appropriately before invoking this method. The method also assumes that the
            client's search function is correctly set up to handle the provided time
            range format.

        Raises:
            Exception: If the search encounters an error or fails, an exception is raised.
        """
        products, _ = self.client.search(
            start=str(between.start),
            end=str(between.end),
            provider=self.provider,
            raise_errors=True,
        )
        return products

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

    # CADIP station host is defined as an environment variable, or 127.0.0.1 by default
    cadip_station_host = os.environ.get("CADIP_STATION_HOST", "127.0.0.1")

    return EOProduct(
        "CADIP",
        {
            "id": file_id,
            "title": download_filename,
            "geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))",
            # TODO build from configuration (but how ?)
            "downloadLink": f"http://{cadip_station_host}:5000/Files({file_id})/$value",
        },
    )
