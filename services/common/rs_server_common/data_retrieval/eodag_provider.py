# Copyright 2023-2026 Airbus, CS Group
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
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from threading import Lock

import yaml
from eodag import EODataAccessGateway, EOProduct, SearchResult
from eodag.config import EODAGSettings
from eodag.plugins.search.qssearch import ODataV4Search
from eodag.utils.exceptions import (
    AuthenticationError,
    MisconfiguredError,
    RequestError,
    ValidationError,
)
from fastapi import HTTPException, status
from rs_server_common.authentication.external_authentication_config import (
    StationExternalAuthenticationConfig,
)
from rs_server_common.stac_cql2 import temporal_operations
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.missions import MISSION_PAIRS, mission_search_params

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
        os.environ["EODAG_EXT_COLLECTIONS_CFG_FILE"] = ""

        # Environment variable values, the last time we checked them. They will be read by eodag.
        self.old_environ = dict(os.environ)

        # Use EODAGSettings(cfg_file=...) instead of the deprecated 'user_conf_file_path'.
        # The first positional arg (config file path) is converted into an EODAGSettings object.
        settings = kwargs.pop("settings", None)
        config_file_path = None

        # Old positional arg: config file path
        if len(args) > 0 and args[0] is not None:
            config_file_path = args[0]
            args = args[1:]

        if settings is None and config_file_path is not None:
            settings = EODAGSettings(cfg_file=config_file_path)

        if settings is not None:
            kwargs["settings"] = settings

        super().__init__(*args, **kwargs)
        self._register_internal_filters()

    def _register_internal_filters(self) -> None:
        """Extend AUXIP/PRIP mappings in memory before this gateway is cached and shared.

        missionFilter holds alternatives of mission pairs; collectionFilter holds
        alternatives of complete collection predicates. Existing station YAMLs need no migration.
        """
        # Add internal filters only to OData V4 searches that map both mission attributes.
        for provider in self._providers.values():
            search = getattr(provider.config, "search", None)
            if (
                search is None
                or search.type != "ODataV4Search"
                or not {"platformShortName", "platformSerialIdentifier"}.issubset(
                    getattr(search, "metadata_mapping", {}),
                )
            ):
                continue

            # Extend a private copy so other providers sharing this configuration are not changed.
            search = deepcopy(search)
            # Read the templates EODAG uses to assemble $filter so internal expressions can be added to its AND group.
            operations = getattr(search, "free_text_search_operations", {}).get("$filter", {}).get("operations", {})
            # Both fragments must be ANDed with the station's other filters.
            # Reject other group layouts rather than changing their Boolean meaning.
            if set(operations) != {"and"} or not isinstance(operations["and"], list):
                raise MisconfiguredError(f"{provider.name}: internal filters require a single OData AND group")

            for name in ("missionFilter", "collectionFilter"):
                # None prevents a separate URL parameter; the placeholder inserts the fragment into $filter.
                # Only the expression is sent to the station, never the internal parameter name.
                search.metadata_mapping[name] = [None, f"$.{name}"]
                operand = f"{{{name}}}"
                if operand not in operations["and"]:
                    operations["and"].append(operand)
            provider.config.search = search

    def __del__(self):
        """Destructor"""
        try:
            shutil.rmtree(self.eodag_cfg_dir.name)  # remove the unique /tmp dir
        except FileNotFoundError:
            pass

    @classmethod
    @lru_cache
    def create(cls, *args, **kwargs) -> "CustomEODataAccessGateway":
        """Return a cached instance of the class."""
        return cls(*args, **kwargs)

    def authenticate_provider(self, provider: str, external_config: StationExternalAuthenticationConfig):
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

            # mandatory keys
            auth_config: dict = {
                "auth_uri": external_config.token_url,
                "refresh_uri": external_config.token_url,
                "req_data": {
                    "client_id": external_config.client_id,
                    "client_secret": external_config.client_secret,
                    "username": external_config.username,
                    "password": external_config.password,
                    "grant_type": external_config.grant_type,
                },
            }

            # Used to set the authorization for token retrieval
            if external_config.authorization is not None:
                auth_config["credentials"] = {"auth_for_token": external_config.authorization}

            # optional keys
            if external_config.scope:
                auth_config["req_data"]["scope"] = external_config.scope

            self.update_providers_config(dict_conf={provider: {"auth": auth_config}})


class EodagProvider(Provider):
    """An EODAG provider.

    It uses EODAG to provide data from external sources.
    """

    def __init__(self, external_config: StationExternalAuthenticationConfig, eodag_config_path: Path, provider: str):
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
            self.client.set_preferred_provider(self.provider)
            self.client.authenticate_provider(self.provider, external_config)
        except Exception as e:
            raise CreateProviderFailed(f"Can't initialize {self.provider} provider") from e

    def _handle_multiple_values(self, mapped_search_args: dict, values: list | str, singular_key: str, plural_key: str):
        """Quote and escape OData literals, choosing the singular (eq) or plural (in) template key."""
        value = values[0] if isinstance(values, list) and len(values) == 1 else values
        key = plural_key if isinstance(value, list) else singular_key
        literals = sorted(value) if isinstance(value, list) else [value]
        mapped_search_args[key] = ",".join("'" + str(v).replace("'", "''") + "'" for v in literals)

    def _map_search_args(self, kwargs: dict) -> dict:  # pylint: disable=too-many-branches
        """Map RS-server fields to EODAG parameters, consuming the converted fields from kwargs.

        The caller forwards both the returned parameters and the remaining kwargs.
        The same conversion is used for a single predicate and for each collection branch.
        """
        mapped_search_args: dict[str, str | None] = {}
        if MISSION_PAIRS in kwargs:
            # Convert pairs only after the request and collection restrictions have been intersected.
            kwargs.update(mission_search_params(kwargs.pop(MISSION_PAIRS)))
        if session_id := kwargs.pop("SessionId", None):
            # Map session_id to the appropriate eodag parameter
            self._handle_multiple_values(mapped_search_args, session_id, "SessionId", "SessionIds")

        if names := kwargs.pop("Name", None):
            if len(names) == 1:
                # Don't use _handle_multiple_values here because the Name template
                # already adds the quotes.
                mapped_search_args["Name"] = names[0]
            else:
                # Group the OR conditions so every name remains subject to the other filters.
                alternatives = " or ".join(f"contains(Name,'{name}')" for name in sorted(names))
                mapped_search_args["NameContains"] = f"({alternatives})"

        if kwargs.pop("sessions_search", False):
            # If request is for session search, handle platform - if any provided.
            if platform := kwargs.pop("Satellite", None):
                self._handle_multiple_values(mapped_search_args, platform, "platform", "platforms")

        for multivalued_key in ("attr_ptype", "platformSerialIdentifier", "platformShortName"):
            # Handle AUXIP/PRIP parameters that can have one or several values
            if values := kwargs.pop(multivalued_key, None):
                self._handle_multiple_values(mapped_search_args, values, multivalued_key, multivalued_key + "s")

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

        date_time = kwargs.pop("DatetimeStart", None)
        if date_time:
            fixed = start = end = None

            if isinstance(date_time, str):
                # Interval: "start/end"
                if "/" in date_time:
                    start, end = date_time.split("/", 1)
                else:
                    # Single instant
                    fixed = date_time

            else:
                # Tuple/list: (fixed, start, end)
                fixed, start, end = (str(date) if date else None for date in date_time)

            mapped_search_args.update(
                {
                    "DatetimeStart": fixed,
                    "Start": start,
                    "End": end,
                },
            )

        start_time = kwargs.pop("Start", None)
        end_time = kwargs.pop("End", None)
        if start_time and end_time:
            mapped_search_args["Start"] = start_time
            mapped_search_args["End"] = end_time
        elif start_time:
            mapped_search_args["DatetimeStart"] = start_time
        elif end_time:
            mapped_search_args["DatetimeEnd"] = end_time

        for op in temporal_operations:
            if query := kwargs.pop(op, None):
                mapped_search_args[op] = query

        if intersects := kwargs.pop("intersects", None):
            mapped_search_args["geometry"] = intersects

        return mapped_search_args

    def _specific_search(self, **kwargs) -> SearchResult | list:  # pylint: disable=too-many-locals
        """Issue one station search, joining complete collection branches with OR before pagination."""
        branches = kwargs.pop("query_branches", None)
        # An empty branch list means no match; an absent key uses the ordinary search parameters.
        if branches == []:
            return []
        mapped_search_args = self._map_search_args(kwargs)

        # Thread-safe access to providers config - avoid dictionary keys changed during iteration
        # error when multiple threads modify providers concurrently.
        with self.client.lock:
            providers = self.client._providers  # pylint: disable=protected-access
            max_items_allowed = int(providers[self.provider].config.search.pagination["max_items_per_page"])
            page_limit = kwargs.pop("limit", None)
            if page_limit is not None:
                limit_value = int(page_limit)
                if limit_value > max_items_allowed:
                    logger.warning(
                        f"Requesting {limit_value} exceeds maximum of {max_items_allowed} "
                        "allowed for this provider!",
                    )
                    logger.warning(f"Number of items per page was set to {max_items_allowed - 1}.")
                    kwargs["limit"] = max_items_allowed - 1
                else:
                    kwargs["limit"] = limit_value

            # Get dataset_key inside the lock
            try:
                prov_cfg = providers[self.provider]
                products_cfg = getattr(prov_cfg.config, "products", {})
                dataset_key = next(iter(products_cfg.keys()))
            except Exception:  # pylint: disable=broad-exception-caught
                dataset_key = "S1_SAR_RAW"  # last-resort fallback

            if branches:
                # Serialize from a snapshot so building branch filters cannot change the shared gateway config.
                search_config = deepcopy(providers[self.provider].config.search)
                search_config.products = deepcopy(getattr(providers[self.provider].config, "products", {}))

        if branches:
            # Each branch combines the request with one collection; map it without changing the original parameters.
            mapped_branches = []
            for branch in branches:
                branch_args = branch.copy()
                mapped_branch = self._map_search_args(branch_args)
                # The mapper removes converted keys; retain the other station parameters alongside its output.
                mapped_branches.append({**branch_args, **mapped_branch})

            # Compare complete mapped values: date bounds are resolved and mission OR groups stay intact.
            # A shared raw date bound alone does not imply that the resulting date predicates are identical.
            common = {
                key: value
                for key, value in mapped_branches[0].items()
                if all(key in branch and branch[key] == value for branch in mapped_branches[1:])
            }

            def serialize_filter(query_args: dict) -> str:
                # Use the station templates without an HTTP call or changes to the shared gateway config.
                serializer = ODataV4Search(self.provider, deepcopy(search_config))
                query, _ = serializer.build_query_string(dataset_key, query_args)
                return " and ".join(query.get("$filter", []))

            # Serialize predicates common to every branch once.
            common_filter = serialize_filter(common)
            filters: list[str] = []
            # Build each OR alternative from its remaining predicates.
            for branch in mapped_branches:
                branch_filter = serialize_filter({key: value for key, value in branch.items() if key not in common})
                if not branch_filter:
                    # One collection adds no restriction beyond the common filters, so the OR is unrestricted.
                    filters = []
                    break
                filters.append(branch_filter)

            # Emit shared predicates once, e.g. geometry AND ((S1A AND type1) OR (S2B AND type2)).
            # Parentheses keep OR groups together when combined with the common AND predicates.
            clauses = [f"({common_filter})"] if common_filter else []
            if filters:
                clauses.append("(" + " or ".join(f"({f})" for f in filters) + ")")
            if clauses:
                mapped_search_args["collectionFilter"] = " and ".join(clauses)

        logger.info(f"Searching from {self.provider} with parameters {mapped_search_args} and kwargs {kwargs}")
        try:
            products = self.client.search(
                **mapped_search_args,  # type: ignore
                provider=self.provider,
                raise_errors=True,
                collection=dataset_key,
                validate=False,  # disable validation to decrease the runtime of the search when in parallel
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
                    "eodag:download_link": f"{base_uri}({product_id})/$value",
                },
            )
        except Exception as e:
            raise CreateProviderFailed(f"Can't initialize {self.provider} download provider") from e
