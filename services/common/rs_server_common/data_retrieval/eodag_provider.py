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
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Dict, List, Union

import yaml
from eodag import EODataAccessGateway, EOProduct, SearchResult
from eodag.api.core import override_config_from_env
from eodag.utils.exceptions import (
    AuthenticationError,
    MisconfiguredError,
    RequestError,
    ValidationError,
)
from fastapi import HTTPException, status
from rs_server_common.utils.logging import Logging

from .provider import CreateProviderFailed, Provider, SearchProductFailed

# from fastapi import HTTPException


logger = Logging.default(__name__)

global_lock = Lock()


class CustomEODataAccessGateway(EODataAccessGateway):
    """EODataAccessGateway with a custom config directory management."""

    def __init__(self, *args, **kwargs):
        """Constructor"""

        self.lock = Lock()

        # Init environment
        self.eodag_cfg_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        os.environ["EODAG_CFG_DIR"] = self.eodag_cfg_dir.name
        # disable product types discovery
        os.environ["EODAG_EXT_PRODUCT_TYPES_CFG_FILE"] = ""

        # Environment variable values, the last time we checked them. They will be read by eodag.
        self.old_environ = dict(os.environ)

        # Init eodag instance
        super().__init__(*args, **kwargs)

    def __del__(self):
        """Destructor"""
        try:
            shutil.rmtree(self.eodag_cfg_dir.name)  # remove the unique /tmp dir
        except FileNotFoundError:
            pass

    @classmethod
    @lru_cache
    def create(cls, *args, **kwargs):
        """Return a cached instance of the class."""
        return cls(*args, **kwargs)

    def override_config_from_env(self):
        """
        Update the eodag conf from the latest EODAG__<provider>__auth__... env vars
        that are set in authentication_to_external.py, if they have changed
        """
        with self.lock:  # safer to use a thread lock before calling eodag and modifying a global var
            if (new_environ := dict(os.environ)) != self.old_environ:
                self.old_environ = new_environ
                override_config_from_env(self.providers_config)


class EodagProvider(Provider):
    """An EODAG provider.

    It uses EODAG to provide data from external sources.
    """

    def __init__(self, config_file: Path, provider: str):  # type: ignore
        """Create a EODAG provider.

        Args:
            config_file: the path to the eodag configuration file
            provider: the name of the eodag provider
        """
        self.provider: str = provider
        self.config_file = config_file.resolve().as_posix()
        try:
            with global_lock:  # use a thread lock before calling the lru_cache
                self.client = CustomEODataAccessGateway.create(self.config_file)
        except Exception as e:
            raise CreateProviderFailed(f"Can't initialize {self.provider} provider") from e
        self.client.set_preferred_provider(self.provider)

        # If the eodag object was already existing and retrieved from the lru_cache,
        # we need to update its configuration from the latest env vars, if they have changed
        self.client.override_config_from_env()

    def _specific_search(self, date_time, **kwargs) -> Union[SearchResult, List]:
        """
        Conducts a search for products within a specified time range.

        This private method interfaces with the client's search functionality,
        retrieving products that fall within the given time range. The 'between'
        parameter is expected to be a TimeRange object, encompassing start and end
        timestamps. The method returns a dictionary of products keyed by their
        respective identifiers.

        Args:
            date_time: An object representing search datetime, can be fixed or open/closed interval.

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
        mapped_search_args: Dict[str, Union[str, None]] = {}

        if session_id := kwargs.pop("id", None):
            # Map session_id to the appropriate eodag parameter
            session_id = session_id[0] if len(session_id) == 1 else session_id
            key = "SessionIds" if isinstance(session_id, list) else "SessionId"
            value = ", ".join(f"'{s}'" for s in session_id) if isinstance(session_id, list) else f"'{session_id}'"
            mapped_search_args[key] = value

        if kwargs.pop("sessions_search", False):
            # If request is for session search, handle platform - if any provided.
            platform = kwargs.pop("platform", None)

            if platform:
                key = "platforms" if isinstance(platform, list) else "platform"
                value = ", ".join(f"'{p}'" for p in platform) if isinstance(platform, list) else f"'{platform}'"
                mapped_search_args[key] = value

            # TODO: check if it is the right way of doing this, looks very cumbersome to do it for every field
            # Tempfix, will be updated, to dirrectly, to verify kwargs and then forward to search.
            if retransfer := kwargs.pop("retransfer", None):
                mapped_search_args["Retransfer"] = str(retransfer).lower()

        if date_time:
            # Since now both for files and sessions, time interval is optional, map it if provided.
            fixed, start, end = [str(date) if date else None for date in date_time]
            mapped_search_args.update(
                {
                    "PublicationDate": fixed,
                    "StartPublicationDate": start,
                    "StopPublicationDate": end,
                },
            )
        try:
            logger.info(f"Searching from {self.provider} with parameters {mapped_search_args}")
            # Start search -> user defined search params in mapped_search_args (id), pagination in kwargs (top, limit).
            # search_method = self.client.search if "session" not in self.provider else self.client.search_iter_page
            products = self.client.search(
                **mapped_search_args,  # type: ignore
                provider=self.provider,
                raise_errors=True,
                productType="S1_SAR_RAW" if "adgs" not in self.provider.lower() else "CAMS_GRF_AUX",
                **kwargs,
            )
            repr(products)  # trigger eodag validation.

        except ValidationError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc
        except (RequestError, MisconfiguredError) as e:
            # invalid token: EODAG returns an exception with "FORBIDDEN" in e.args when the token key is invalid.
            if e.args and "FORBIDDEN" in e.args[0]:
                raise SearchProductFailed(
                    f"Can't search provider {self.provider} " "because the used token is not valid",
                ) from e
            logger.debug(e)
            raise SearchProductFailed(e) from e
        except AuthenticationError as exc:
            raise ValueError("EoDAG could not authenticate") from exc

        if products.number_matched:
            logger.info(f"Returned {products.number_matched} session from {self.provider}")

        if products.errors:
            logger.error(f"Errors from {self.provider}: {products.errors}")
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
        # Dirty fix for eodag: change extension
        org_file = to_file
        to_file = to_file.with_suffix(to_file.suffix + "_fix_eodag")

        # Use thread-lock because self.client.download is not thread-safe
        with self.client.lock:
            product = self.create_eodag_product(product_id, to_file.name)
            # download_plugin = self.client._plugins_manager.get_download_plugin(product)
            # authent_plugin = self.client._plugins_manager.get_auth_plugin(product.provider)
            # product.register_downloader(download_plugin, authent_plugin)
            self.client.download(product, output_dir=str(to_file.parent))

            # Dirty fix continued: rename the download directory
            if to_file.is_dir() and (not org_file.is_dir()):
                to_file.rename(org_file)

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
