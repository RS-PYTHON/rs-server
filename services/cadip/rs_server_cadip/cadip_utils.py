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

"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""

import json
import os
import os.path as osp
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import eodag
import stac_pydantic
import starlette.requests
import yaml
from pydantic import BaseModel
from stac_pydantic.shared import Asset

DEFAULT_GEOM = {"geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))"}
CADIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
search_yaml = CADIP_CONFIG / "cadip_search_config.yaml"


class CADIPQueryableField(BaseModel):
    """BaseModel used to describe queryable item."""

    title: str
    type: str
    description: Optional[str] = None
    format: Optional[str] = None
    items: Optional[dict] = None


def generate_queryables(collection_id: str) -> dict[str, CADIPQueryableField]:
    """Function used to get available queryables based on a given collection."""
    config = select_config(collection_id)
    if config:
        # Top and limit are pagination-related quaryables, remove if there.
        if isinstance(config.get("query"), dict):
            config["query"].pop("limit", None)
            config["query"].pop("top", None)
        # Get all defined quaryables.
        all_queryables = get_cadip_queryables()
        # Remove the ones already defined, and keep only the ones that can be added.
        for key in set(config["query"].keys()).intersection(set(all_queryables.keys())):
            all_queryables.pop(key)
        return all_queryables
    # If config is not found, return all available queryables.
    return get_cadip_queryables()


def get_cadip_queryables() -> dict[str, CADIPQueryableField]:
    """Function to list all available queryables for CADIP session search."""
    return {
        "PublicationDate": CADIPQueryableField(
            title="PublicationDate",
            type="Interval",
            description="Session Publication Date",
            format="1940-03-10T12:00:00Z/2024-01-01T12:00:00Z",
        ),
        "Satellite": CADIPQueryableField(
            title="Satellite",
            type="[string, array]",
            description="Session satellite acquisition target",
            format="S1A or S1A, S2B",
        ),
        "SessionId": CADIPQueryableField(
            title="SessionId",
            type="[string, array]",
            description="Session ID descriptor",
            format="S1A_20231120061537234567",
        ),
    }


@lru_cache(maxsize=1)
def read_conf():
    """Used each time to read RSPY_CADIP_SEARCH_CONFIG config yaml."""
    cadip_search_config = os.environ.get("RSPY_CADIP_SEARCH_CONFIG", str(search_yaml.absolute()))
    with open(cadip_search_config, encoding="utf-8") as search_conf:
        config = yaml.safe_load(search_conf)
    return config


def select_config(configuration_id: str) -> dict | None:
    """Used to select a specific configuration from yaml file, returns None if not found."""
    return next(
        (item for item in read_conf()["collections"] if item["id"] == configuration_id),
        None,
    )


def prepare_cadip_search(collection, queryables):
    """Function used to prepare cadip /search endpoint.
    Map queryables from stac to odata format, read and update existing configuration.
    """

    selected_config = select_config(collection)

    stac_mapper_path = CADIP_CONFIG / "cadip_sessions_stac_mapper.json"
    with open(stac_mapper_path, encoding="utf-8") as stac_map:
        stac_mapper = json.loads(stac_map.read())
        query_params = {stac_mapper.get(k, k): v for k, v in queryables.items()}

    if selected_config:
        # Update selected_config query values with the ones coming in request.query_params
        for query_config_key in query_params:
            selected_config["query"][query_config_key] = query_params[query_config_key]
    return selected_config, query_params


def rename_keys(product: dict) -> dict:
    """Rename keys in the product dictionary. To match eodag specific properties key name (id / startTime..)"""
    if "Id" in product:
        product["id"] = product.pop("Id")
    if "PublicationDate" in product:
        product["startTimeFromAscendingNode"] = product["PublicationDate"]
    return product


def update_product(product: dict) -> dict:
    """Update product with renamed keys and default geometry."""
    product = rename_keys(product)
    product.update(DEFAULT_GEOM)
    return product


def map_dag_file_to_asset(mapper: dict, product: eodag.EOProduct, request: starlette.requests.Request) -> Asset:
    """This function is used to map extended files from odata to stac format."""
    asset = {map_key: product.properties[map_value] for map_key, map_value in mapper.items()}
    href = f'{request.url.scheme}://{request.url.netloc}/cadip/cadu?name={asset.pop("id")}'
    return Asset(href=href, roles=["cadu"], title=product.properties["Name"], **asset)


def from_session_expand_to_dag_serializer(input_sessions: List[eodag.EOProduct]) -> List[eodag.EOProduct]:
    """
    Convert a list of sessions containing expanded files metadata into a list of files for serialization into the DB.
    """
    return [
        eodag.EOProduct(provider="internal_session_product_file_from_cadip", properties=update_product(product))
        for session in input_sessions
        for product in session.properties.get("Files", [])
    ]


def from_session_expand_to_assets_serializer(
    feature_collection: stac_pydantic.ItemCollection,
    input_session: eodag.EOProduct,
    mapper: dict,
    request: starlette.requests.Request,
) -> stac_pydantic.ItemCollection:
    """
    Associate all expanded files with session from feature_collection and create a stac_pydantic.Asset for each file.
    """
    for session in feature_collection.features:
        # Iterate over products and map them to assets
        for product in input_session:
            if product.properties["SessionID"] == session.id:
                # Create Asset
                asset: Asset = map_dag_file_to_asset(mapper, product, request)
                # Add Asset to Item.
                session.assets.update({asset.title: asset.model_dump()})  # type: ignore
        # Remove processed products from input_session
        input_session = [product for product in input_session if product.properties["SessionID"] != session.id]

    return feature_collection


def validate_products(products: eodag.EOProduct):
    """Function used to remove all miconfigured outputs."""
    valid_eo_products = []
    for product in products:
        try:
            str(product)
            valid_eo_products.append(product)
        except eodag.utils.exceptions.MisconfiguredError:
            continue
    return valid_eo_products
