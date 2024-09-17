# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""EODAG Provider."""

import os
import shutil
import tempfile
from pathlib import Path
from threading import Lock
from typing import List, Union

import yaml
from eodag import EODataAccessGateway, EOProduct, SearchResult
from eodag.utils.exceptions import RequestError

from .provider import CreateProviderFailed, Provider, TimeRange

# TODO: See TODO invalid token. Import 'from .provider SearchProductFailed' if needed

# from fastapi import HTTPException


class EodagProvider(Provider):
    """An EODAG provider.

    It uses EODAG to provide data from external sources.
    """

    lock = Lock()  # static Lock instance

    def __init__(self, config_file: Path, provider: str):
        """Create a EODAG provider.

        Args:
            config_file: the path to the eodag configuration file
            provider: the name of the eodag provider
        """
        self.eodag_cfg_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.provider: str = provider
        self.config_file = config_file
        self.client: EODataAccessGateway = self.init_eodag_client(config_file)
        self.client.set_preferred_provider(self.provider)

    def __del__(self):
        """Destructor"""
        try:
            shutil.rmtree(self.eodag_cfg_dir.name)  # remove the unique /tmp dir
        except FileNotFoundError:
            pass

    def init_eodag_client(self, config_file: Path) -> EODataAccessGateway:
        """Initialize the eodag client.

        The EODAG client is initialized for the given provider.

        Args:
            config_file: the path to the eodag configuration file

        Returns:
             the initialized eodag client
        """
        try:
            # Use thread-lock
            with EodagProvider.lock:
                os.environ["EODAG_CFG_DIR"] = self.eodag_cfg_dir.name
                # disable product types discovery
                os.environ["EODAG_EXT_PRODUCT_TYPES_CFG_FILE"] = ""
                return EODataAccessGateway(config_file.as_posix())
        except Exception as e:
            raise CreateProviderFailed(f"Can't initialize {self.provider} provider") from e

    def _specific_search(self, between: TimeRange, **kwargs) -> Union[SearchResult, List]:
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
            SearchResult: A dictionary where keys are product identifiers and
                            values are EOProduct instances.

        Note:
            The time format of the 'between' parameter should be verified or formatted
            appropriately before invoking this method. The method also assumes that the
            client's search function is correctly set up to handle the provided time
            range format.

        Raises:
            Exception: If the search encounters an error or fails, an exception is raised.
        """
        mapped_search_args = {}
        sessions_search = kwargs.pop("sessions_search", False)

        session_id = kwargs.pop("id", None)
        if session_id:
            # If request contains session id, map it to eodag parameter accordingly (SessionID for single, Ids for list)
            if isinstance(session_id, list):
                mapped_search_args["SessionIds"] = ", ".join(session_id)
            elif isinstance(session_id, str):
                mapped_search_args["SessionID"] = session_id

        if sessions_search:
            # If request is for session search, handle platform - if any provided.
            platform = kwargs.pop("platform", None)

            # Very annoying, for files odata is **SessionID**, for sessions is **SessionId**
            if "SessionID" in mapped_search_args:
                mapped_search_args["SessionId"] = mapped_search_args.pop("SessionID")
            if platform:
                if isinstance(platform, list):
                    mapped_search_args["platforms"] = ", ".join(platform)
                elif isinstance(platform, str):
                    mapped_search_args["platform"] = platform

        if between:
            # Since now both for files and sessions, time interval is optional, map it if provided.
            mapped_search_args.update(
                {
                    "startTimeFromAscendingNode": str(between.start),
                    "completionTimeFromAscendingNode": str(between.end),
                },
            )

        try:
            # Start search -> user defined search params in mapped_search_args (id), pagination in kwargs (top, limit).
            products = self.client.search(
                **mapped_search_args,  # type: ignore
                provider=self.provider,
                raise_errors=True,
                productType="S1_SAR_RAW" if "adgs" not in self.provider.lower() else "CAMS_GRF_AUX",
                **kwargs,
            )
        except RequestError:
            # except RequestError as e:
            # TODO invalid token: EODAG returns an exception with "FORBIDDEN" in e.args when the token key is invalid.
            # Should we handle this specifically by raising an exception, or follow the current approach
            # where any error results in returning an empty list?
            # if e.args and "FORBIDDEN" in e.args[0]:
            #     raise SearchProductFailed(
            #         f"Can't search provider {self.provider} " "because the used token is not valid",
            #     ) from e
            # Empty list if something goes wrong in eodag
            return []

        return products

    def download(self, product_id: str, to_file: Path) -> None:
        """Download the expected product at the given local location.

        EODAG needs an EOProduct to download.
        We build an EOProduct from the id and download location
        to be able to call EODAG for download.


        Args:
            product_id: the id of the product to download
            to_file: the path where the product has to be download

        Returns:
            None

        """
        product = self.create_eodag_product(product_id, to_file.name)
        # download_plugin = self.client._plugins_manager.get_download_plugin(product)
        # authent_plugin = self.client._plugins_manager.get_auth_plugin(product.provider)
        # product.register_downloader(download_plugin, authent_plugin)
        self.client.download(product, output_dir=str(to_file.parent))

    def create_eodag_product(self, product_id: str, filename: str):
        """Initialize an EO product with minimal properties.

        The title is used by EODAG as the name of the downloaded file.
        The download link is used by EODAG as http request url for download.
        The geometry is mandatory in an EO Product so we add the all earth as geometry.

        Args:
            product_id (str): the id of EO Product
            filename (str): the name of the downloaded file

        Returns:
            product (EOProduct): the initialized EO Product

        """
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                base_uri = yaml.safe_load(f)[self.provider.lower()]["download"]["base_uri"]
            return EOProduct(
                self.provider,
                {
                    "id": product_id,
                    "title": filename,
                    "geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))",
                    # TODO build from configuration (but how ?)
                    "downloadLink": f"{base_uri}({product_id})/$value",
                },
            )
        except Exception as e:
            raise CreateProviderFailed(f"Can't initialize {self.provider} download provider") from e
