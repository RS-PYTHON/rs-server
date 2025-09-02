# /rs_server_prip/prip_utils.py

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
"""
Module for interacting with ADGS system through a FastAPI APIRouter.

This module mirrors rs_server_adgs.adgs_utils but adapts for PRIP:
- different env/config names (RSPY_PRIP_*), default config file: `prip_search_config.yaml`
- PRIP-specific STAC→OData mapper file name: `prip_stac_mapper.json` (falls back to `adgs_stac_mapper.json`)
- asset serialization emits a single asset (named after the item id) with roles ["data","metadata"]
  and an href that points to the OData $value endpoint.
- platform/constellation mapping helpers reuse the common `map_stac_platform()` table.
"""
from __future__ import annotations

import json
import os
import os.path as osp
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import stac_pydantic
import yaml
from fastapi import HTTPException, status
from rs_server_common.stac_api_common import QueryableField, map_stac_platform

PRIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
search_yaml = PRIP_CONFIG / "prip_search_config.yaml"


# ----------------------
# Config loaders
# ----------------------
@lru_cache
def read_conf():
    """Used each time to read RSPY_ADGS_SEARCH_CONFIG config yaml."""
    prip_search_config = os.environ.get("RSPY_PRIP_SEARCH_CONFIG", str(search_yaml.absolute()))
    with open(prip_search_config, encoding="utf-8") as search_conf:
        config = yaml.safe_load(search_conf)
    return config  # WARNING: if the caller wants to modify this cached object, it must deepcopy it first


@lru_cache
def prip_odata_to_stac_template():
    """Used each time to read the ODataToSTAC_template json template."""
    with open(PRIP_CONFIG / "ODataToSTAC_template.json", encoding="utf-8") as mapper:
        config = json.loads(mapper.read())
    return config  # WARNING: if the caller wants to modify this cached object, he must deepcopy it first


@lru_cache
def prip_stac_mapper():
    """Used each time to read the adgs_stac_mapper config yaml."""
    with open(PRIP_CONFIG / "prip_stac_mapper.json", encoding="utf-8") as stac_map:
        config = json.loads(stac_map.read())
    return config  # WARNING: if the caller wants to modify this cached object, it must deepcopy it first


def select_config(configuration_id: str) -> dict | None:
    """Used to select a specific configuration from yaml file, returns None if not found."""
    return next(
        (item for item in read_conf()["collections"] if item["id"] == configuration_id),
        None,
    )


def stac_to_odata(stac_params: dict) -> dict:
    """Convert a parameter directory from STAC keys to OData keys. Return the new directory."""
    return {prip_stac_mapper().get(stac_key, stac_key): value for stac_key, value in stac_params.items()}


# ----------------------
# STAC asset post-processing
# ----------------------
def serialize_prip_asset(feature_collection: stac_pydantic.ItemCollection, products: list[dict[str, Any]]):
    """Finalize assets for each STAC feature based on OData product metadata.

    - Set href to the download link of the matched OData product (Products({Id})/$value).
    - Rename default "file" asset to the item id (without extension).
    - Ensure roles ["data","metadata"] as per STAC-PRIP-ITEM-REQ-0090.
    """
    for feature in feature_collection.features:
        prip_id = feature.properties.dict().get("prip:id") or feature.id
        # Find matching product by id
        # matched = next((p for p in products if p.get("properties", {}).get("id") == prip_id), None)
        matched = next((p for p in products if p.properties.get("Name") == prip_id), None)
        if not matched:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unable to map product for feature {feature.id}",
            )
        # href = matched.get("properties", {}).get("href")
        href = matched.properties.get("href")
        if not href:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Missing download href for product {prip_id}",
            )

        # Update asset href and rename to item id
        feature.assets["file"].href = re.sub(r"\([^\)]*\)", f"({prip_id})", href)
        new_key = (feature.id or prip_id).rsplit(".", 1)[0]
        feature.assets[new_key] = feature.assets.pop("file")
        # roles: ["data","metadata"]
        asset = feature.assets[new_key]

        asset.extra_fields = {}

        roles = list(dict.fromkeys((asset.extra_fields or {}).get("roles", []) + ["data", "metadata"]))  # unique
        asset.extra_fields = {**(asset.extra_fields or {}), "roles": roles}
        # Normalize item id (drop extension if any)
        feature.id = new_key

    return feature_collection


def get_prip_queryables() -> dict[str, QueryableField]:
    """Function to list all available queryables for PRIP file search."""
    return {
        "PublicationDate": QueryableField(
            title="PublicationDate",
            type="Interval",
            description="File Publication Date",
            format="1940-03-10T12:00:00Z/2024-01-01T12:00:00Z",
        ),
        "processingDate": QueryableField(
            title="Processing Date",
            type="DateTimeOffset",
            description="Auxip processing date",
            format="2019-02-16T12:00:00.000Z",
        ),
        "platformSerialIdentifier": QueryableField(
            title="Platform Serial Identifier",
            type="StringAttribute",
            description="Mission identifier (A/B/C)",
            format="A / B / C",
        ),
        "platformShortName": QueryableField(
            title="Platform Short Name",
            type="StringAttribute",
            description="Platform Short name",
            format="SENTINEL-2 / SENTINEL-1",
        ),
        "constellation": QueryableField(
            title="constellation",
            type="StringAttribute",
            description="constellation name",
            format="SENTINEL-2 / SENTINEL-1",
        ),
    }


# ----------------------
# Platform mapping utilities
# ----------------------
def prip_map_mission(platform: str, constellation: str) -> tuple[str | None, str | None]:
    """
    Custom function for PRIP, to read constellation mapper and return propper
    values for platform and serial.
    Eodag maps this values to platformShortName, platformSerialIdentifier

    Input: platform = sentinel-1a       Output: sentinel-1, A
    Input: platform = sentinel-5P       Output: sentinel-5p, None
    Input: constellation = sentinel-1   Output: sentinel-1, None
    """
    data = map_stac_platform()
    platform_short_name: str | None = None
    platform_serial_identifier: str | None = None
    try:
        if platform:
            config = next(satellite[platform] for satellite in data["satellites"] if platform in satellite)
            platform_short_name = config.get("constellation", None)
            platform_serial_identifier = config.get("serialid", None)
        if constellation:
            if platform_short_name and platform_short_name != constellation:
                # Inconsistent combination of platform / constellation case
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid combination of platform-constellation",
                )
            if any(
                satellite[list(satellite.keys())[0]]["constellation"] == constellation
                for satellite in data["satellites"]
            ):
                platform_short_name = constellation
                platform_serial_identifier = None
            else:
                raise KeyError
    except (KeyError, IndexError, StopIteration) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot map platform/constellation",
        ) from exc
    return platform_short_name, platform_serial_identifier


def prip_reverse_map_mission(
    platform: str | None,
    constellation: str | None,
) -> tuple[str | None, str | None]:
    """Function used to re-map platform and constellation based on satellite value."""
    if not (constellation or platform):
        return None, None

    if constellation:
        constellation = constellation.lower()  # type: ignore

    for satellite in map_stac_platform()["satellites"]:
        for key, info in satellite.items():
            # Check for matching serialid and constellation
            if info.get("serialid") == platform and info.get("constellation").lower() == constellation:
                return key, info.get("constellation")
    return None, None


def prepare_collection(collection: stac_pydantic.ItemCollection) -> stac_pydantic.ItemCollection:
    """Used to create a more complex mapping on platform/constallation from odata to stac."""
    for feature in collection.features:
        feature.properties.platform, feature.properties.constellation = prip_reverse_map_mission(
            feature.properties.platform,
            feature.properties.constellation,
        )
    return collection
