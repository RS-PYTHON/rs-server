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
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple, Union

import eodag
import yaml
from fastapi import HTTPException, status
from rs_server_common.stac_api_common import map_stac_platform
from rs_server_common.utils.logging import Logging
from stac_pydantic import ItemCollection, ItemProperties
from stac_pydantic.shared import Asset

DEFAULT_GEOM = {"geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))"}
CADIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
search_yaml = CADIP_CONFIG / "cadip_search_config.yaml"

logger = Logging.default(__name__)


@lru_cache()
def read_conf():
    """Used each time to read RSPY_CADIP_SEARCH_CONFIG config yaml."""
    cadip_search_config = os.environ.get("RSPY_CADIP_SEARCH_CONFIG", str(search_yaml.absolute()))
    with open(cadip_search_config, encoding="utf-8") as search_conf:
        config = yaml.safe_load(search_conf)
    return config  # WARNING: if the caller wants to modify this cached object, it must deepcopy it first


def select_config(configuration_id: str) -> dict | None:
    """Used to select a specific configuration from yaml file, returns None if not found."""
    return next(
        (item for item in read_conf()["collections"] if item["id"] == configuration_id),
        None,
    )


def stac_to_odata(stac_params: dict) -> dict:
    """Convert a parameter directory from STAC keys to OData keys. Return the new directory."""
    stac_mapper_path = CADIP_CONFIG / "cadip_sessions_stac_mapper.json"
    with open(stac_mapper_path, encoding="utf-8") as stac_map:
        stac_mapper = json.loads(stac_map.read())
        return {stac_mapper.get(stac_key, stac_key): value for stac_key, value in stac_params.items()}


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
    product["href"] = re.sub(r"\([^\)]*\)", f'({product["id"]})', product["href"])
    return product


def map_dag_file_to_asset(mapper: dict, product: eodag.EOProduct, href: str) -> Asset:
    """This function is used to map extended files from odata to stac format."""
    asset = {map_key: product.properties[map_value] for map_key, map_value in mapper.items()}
    href = re.sub(r"\([^\)]*\)", f'({product.properties["id"]})', href)
    asset.pop("id")
    return Asset(href=href, roles=["cadu"], title=product.properties["Name"], **asset)


def from_session_expand_to_dag_serializer(input_sessions: List[eodag.EOProduct]) -> List[eodag.EOProduct]:
    """
    Convert a list of sessions containing expanded files metadata into a list of files for serialization into the DB.
    """
    return [
        eodag.EOProduct(
            provider="internal_session_product_file_from_cadip",
            properties=update_product(session.properties),
        )
        for session in input_sessions
    ]


def from_session_expand_to_assets_serializer(
    feature_collection: ItemCollection,
    input_session: eodag.EOProduct,
    mapper: dict,
) -> ItemCollection:
    """
    Associate all expanded files with session from feature_collection and create a stac_pydantic.Asset for each file.
    """
    for session in feature_collection.features:
        # Iterate over products and map them to assets
        for product in input_session:
            if product.properties["SessionId"] == session.id:
                # Create Asset
                asset: Asset = map_dag_file_to_asset(mapper, product, product.properties["href"])
                # Add Asset to Item.
                session.assets.update({asset.title or "": asset})
        # Remove processed products from input_session
        input_session = [product for product in input_session if product.properties["SessionId"] != session.id]

    return feature_collection


def validate_products(products: eodag.EOProduct):
    """Function used to remove all miconfigured outputs."""
    valid_eo_products = []
    for product in products:
        try:
            str(product)
            valid_eo_products.append(product)
        except eodag.utils.exceptions.MisconfiguredError as e:
            logger.warning(e)
            continue
    return valid_eo_products


def cadip_map_mission(platform: str, constellation: str):
    """
    Map STAC platform and constellation into OData Satellite.

    Input: platform = sentinel-1a       Output: A
    Input: constellation = sentinel-1   Output: A, B, C
    """
    data: dict = map_stac_platform()
    satellite: Union[None, str] = None
    satellites: Union[None, str] = None
    try:
        if platform:
            config = next(sat[platform] for sat in data["satellites"] if platform in sat)
            satellite = config.get("code", None)
        if constellation:
            satellites = ", ".join(
                [
                    satellite_info["code"]
                    for satellite in data["satellites"]
                    for satellite_info in satellite.values()
                    if satellite_info.get("constellation") == constellation
                ],
            )
            if satellite and satellite not in satellites:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid combination of platform-constellation",
                )
    except (KeyError, IndexError, StopIteration) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot map platform/constellation",
        ) from exc
    return satellite or satellites


def cadip_reverse_map_mission(platform: Union[str, None]) -> Tuple[Union[str, None], Union[str, None]]:
    """Function used to re-map platform and constellation based on satellite value."""
    if not platform:
        return None, None
    for satellite in map_stac_platform()["satellites"]:
        for key, info in satellite.items():
            if info.get("code") == platform:
                return key, info.get("constellation")
    return None, None


def link_assets_to_session(session_data, assets_dict, mapper):
    """Function used to allocate assets to propper session item based on session id property."""
    # Validity check to be later added.
    for feature in session_data.features:
        matching_assets = [asset_item for asset_item in assets_dict if feature.id == asset_item["SessionId"]]
        for asset_item in matching_assets:
            asset_dict = {
                map_key: asset_item[map_value] for map_key, map_value in mapper.items() if map_value in asset_item
            }
            asset: Asset = Asset(title=asset_dict.pop("id"), roles=["cadu"], **asset_dict)
            if asset.title:
                feature.assets.update({asset.title: asset})
            else:
                logger.error(f"Ignored CADU asset without title: {asset}")
        try:
            properties: ItemProperties = feature.properties
            start_date = properties.start_datetime
            end_date = max(
                (
                    datetime.fromisoformat(item["PublicationDate"].replace("Z", "")).replace(tzinfo=timezone.utc)
                    for item in matching_assets
                ),
                default=None,
            )
            # https://github.com/radiantearth/stac-spec/blob/master/commons/common-metadata.md#date-and-time-range
            # Using one of the fields REQUIRES inclusion of the other field as well to enable a user to search STAC
            # records by the provided times. So if you use start_datetime you need to add end_datetime and vice-versa.
            if start_date and end_date:
                properties.end_datetime = end_date.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"  # type: ignore
            elif start_date or end_date:
                logger.warning(f"{feature.id} has only one time range property: {start_date}/{end_date}")
                properties.start_datetime = None
                properties.end_datetime = None
        except ValueError as e:
            logger.warning(f"Cannot update start/end datetime for {feature.id}: {e}")
            continue
    return session_data


def prepare_collection(collection: ItemCollection) -> ItemCollection:
    """Used to create a more complex mapping on platform/constallation from odata to stac."""
    for feature in collection.features:
        feature.properties.platform, feature.properties.constellation = cadip_reverse_map_mission(
            feature.properties.platform,
        )
    return collection
