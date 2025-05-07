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

import yaml
from eodag import EODataAccessGateway, EOProduct, SearchResult
from eodag.utils.exceptions import (
    AuthenticationError,
    MisconfiguredError,
    RequestError,
    ValidationError,
)
from fastapi import HTTPException, status
from rs_server_common.authentication.external_authentication_config import (
    ExternalAuthenticationConfig,
)
from rs_server_common.authentication.token_auth import get_station_token
from rs_server_common.settings import env_bool
from rs_server_common.stac_cql2 import temporal_operations
from rs_server_common.utils.logging import Logging

from .provider import CreateProviderFailed, Provider, SearchProductFailed

logger = Logging.default(__name__)

global_lock = Lock()


class CustomEODataAccessGateway(EODataAccessGateway):
    """EODataAccessGateway with a custom config directory management."""

    def __init__(self, *args, **kwargs):
        """Constructor"""

        self.lock = Lock()
        self.all_auth_providers = []  # all authenticated providers

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

    def authenticate_provider(self, provider: str, external_config: ExternalAuthenticationConfig):
        """
        Set the authentication for an external provider (=station).

        Args:
            provider: the name of the eodag provider (=station name)
            external_config: external provider (=station) authentication from rs-server.yaml file
            or RSPY__TOKEN__xxx env vars
        """

        # In a lock, call this function only once by provider, to avoid changing the config
        # and using it (when calling a search) at the same time.
        with self.lock:
            if provider in self.all_auth_providers:
                return
            self.all_auth_providers.append(provider)

            provider_config = self.providers_config[provider]
            if env_bool("RSPY_USE_MODULE_FOR_STATION_TOKEN", default=False):
                provider_config.update(
                    {"auth": {"credentials": {"token": get_station_token(external_config, {})["access_token"]}}},
                )
            else:
                # mandatory keys
                provider_config.update(
                    {
                        "auth": {
                            "auth_uri": external_config.token_url,
                            "refresh_uri": external_config.token_url,
                            "req_data": {
                                "client_id": external_config.client_id,
                                "client_secret": external_config.client_secret,
                                "username": external_config.username,
                                "password": external_config.password,
                                "grant_type": external_config.grant_type,
                            },
                        },
                    },
                )

                # Used to set the authorization for token retrieval
                if external_config.authorization is not None:
                    provider_config.update({"auth": {"credentials": {"auth_for_token": external_config.authorization}}})

                # optional keys
                if external_config.scope:
                    provider_config.update({"auth": {"req_data": {"scope": external_config.scope}}})


class EodagProvider(Provider):
    """An EODAG provider.

    It uses EODAG to provide data from external sources.
    """

    def __init__(self, external_config: ExternalAuthenticationConfig, eodag_config_path: Path, provider: str):
        """Create a EODAG provider.

        Args:
            external_config: external provider (=station) authentication from rs-server.yaml file
            or RSPY__TOKEN__xxx env vars. Override values from the eodag config file (below).
            eodag_config_path: path to the eodag configuration file (adgs_ws_config.yaml or cadip_ws_config.yaml)
            provider: the name of the eodag provider (=station name)
        """
        self.provider: str = provider
        self.eodag_config_path = eodag_config_path.resolve().as_posix()
        try:
            with global_lock:  # use a thread lock before calling the lru_cache
                self.client = CustomEODataAccessGateway.create(self.eodag_config_path)
        except Exception as e:
            raise CreateProviderFailed(f"Can't initialize {self.provider} provider") from e
        self.client.set_preferred_provider(self.provider)
        self.client.authenticate_provider(self.provider, external_config)

    def _specific_search(self, **kwargs) -> SearchResult | list:  # pylint: disable=too-many-branches,too-many-locals
        """
        Conducts a search for products using the specified OData arguments.

        This private method interfaces with the EODAG client's search functionality
        to retrieve products that match the given search parameters. It handles
        special cases such as `PublicationDate` and session ID lists while enforcing
        pagination constraints as per provider limitations.

        Args:
            **kwargs: Arbitrary keyword arguments specifying search parameters,
                including all queryables defined in the provider's configuration as OData arguments.

        Returns:
            Union[SearchResult, List]: A `SearchResult` object containing the matched products
            or an empty list if no matches are found.

        Raises:
            HTTPException: If a validation error occurs in the search query.
            SearchProductFailed: If the search request fails due to request errors,
                misconfiguration, or authentication issues.
            ValueError: If authentication with EODAG fails.

        Notes:
            - Ensures compliance with provider-specific constraints, such as pagination limits.
            - Logs encountered errors and provides detailed messages in case of failures.
        """

        mapped_search_args: dict[str, str | None] = {}
        if session_id := kwargs.pop("SessionId", None):
            # Map session_id to the appropriate eodag parameter
            session_id = session_id[0] if len(session_id) == 1 else session_id
            key = "SessionIds" if isinstance(session_id, list) else "SessionId"
            value = ", ".join(f"'{s}'" for s in session_id) if isinstance(session_id, list) else f"'{session_id}'"
            mapped_search_args[key] = value

        if kwargs.pop("sessions_search", False):
            # If request is for session search, handle platform - if any provided.
            platform = kwargs.pop("Satellite", None)

            if platform:
                key = "platforms" if isinstance(platform, list) else "platform"
                value = ", ".join(f"'{p}'" for p in platform) if isinstance(platform, list) else f"'{platform}'"
                mapped_search_args[key] = value

        if date_time := kwargs.pop("PublicationDate", False):
            # Since now both for files and sessions, time interval is optional, map it if provided.
            fixed, start, end = (str(date) if date else None for date in date_time)
            mapped_search_args.update(
                {
                    "PublicationDate": fixed,
                    "StartPublicationDate": start,
                    "StopPublicationDate": end,
                },
            )

        for op in temporal_operations:
            if query := kwargs.pop(op, None):
                mapped_search_args[op] = query

        max_items_allowed = int(self.client.providers_config[self.provider].search.pagination["max_items_per_page"])
        if int(kwargs["items_per_page"]) > max_items_allowed:
            logger.warning(
                f"Requesting {kwargs['items_per_page']} exceeds maximum of {max_items_allowed} "
                "allowed for this provider!",
            )
            logger.warning(f"Number of items per page was set to {max_items_allowed - 1}.")
            kwargs["items_per_page"] = max_items_allowed - 1
        try:
            logger.info(f"Searching from {self.provider} with parameters {mapped_search_args} and kwargs {kwargs}")
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
            with open(self.eodag_config_path, encoding="utf-8") as f:
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
