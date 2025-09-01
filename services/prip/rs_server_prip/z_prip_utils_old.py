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

# Resolve the config directory colocated with the package
PRIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
search_yaml = PRIP_CONFIG / "prip_search_config.yaml"


# ----------------------
# Config loaders
# ----------------------
@lru_cache
def read_conf():
    """Used each time to read RSPY_PRIP_SEARCH_CONFIG config yaml."""
    prip_search_config = Path(os.environ.get("RSPY_PRIP_SEARCH_CONFIG", str(search_yaml.absolute())))
    with open(prip_search_config, encoding="utf-8") as search_conf:
        config = yaml.safe_load(search_conf)
    return config # WARNING: if the caller wants to modify this cached object, it must deepcopy it first


@lru_cache
def prip_odata_to_stac_template():
    """Used each time to read the ODataToSTAC_template json template."""
    with open(PRIP_CONFIG / "ODataToSTAC_template.json", encoding="utf-8") as mapper:
        config = json.loads(mapper.read())
    return config  # WARNING: if the caller wants to modify this cached object, he must deepcopy it first


@lru_cache
def prip_stac_mapper():
    """Used each time to read the prip_stac_mapper config yaml."""
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
        prip_id = feature.properties.dict()["prip:id"]
        # Find matching product by id
        matched = next((p for p in products if p.get("properties", {}).get("id") == prip_id), None)
        if not matched:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unable to map product for feature {feature.id}",
            )
        href = matched.get("properties", {}).get("href")
        if not href:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Missing download href for product {prip_id}",
            )

        # Update asset href and rename to item id
        feature.assets["file"].href = re.sub(r"\([^\)]*\)", f"({prip_id})", href)
        new_key = (feature.id or    prip_id).rsplit(".", 1)[0]
        feature.assets[new_key] = feature.assets.pop("file")
        # roles: ["data","metadata"]
        asset = feature.assets[new_key]
        roles = list(dict.fromkeys((asset.extra_fields or {}).get("roles", []) + ["data", "metadata"]))  # unique
        asset.extra_fields = {**(asset.extra_fields or {}), "roles": roles}
        # Normalize item id (drop extension if any)
        feature.id = new_key

    return feature_collection


# ----------------------
# Queryables
# ----------------------
def get_prip_queryables() -> dict[str, QueryableField]:
    """List queryables exposed by the PRIP Item Search surface.
    These names are STAC-facing and will be translated by `prip_stac_mapper`.
    """
    return {
        "published": QueryableField(
            title="published",
            type="Interval",
            description="Product publication (ingestion) time interval",
            format="2019-02-16T12:00:00Z/2025-01-01T12:00:00Z",
        ),
        "datetime": QueryableField(
            title="datetime",
            type="Interval",
            description="Acquisition time interval",
            format="2024-01-01T00:00:00Z/2024-12-31T23:59:59Z",
        ),
        "start_datetime": QueryableField(
            title="start_datetime",
            type="DateTime",
            description="Acquisition start time",
            format="2024-01-01T00:00:00Z",
        ),
        "end_datetime": QueryableField(
            title="end_datetime",
            type="DateTime",
            description="Acquisition end time",
            format="2024-01-02T00:00:00Z",
        ),
        "processing:datetime": QueryableField(
            title="processing:datetime",
            type="DateTime",
            description="Processing completion time",
            format="2024-01-01T12:34:56Z",
        ),
        "product:type": QueryableField(
            title="product:type",
            type="StringAttribute",
            description="New PRIP product type (e.g., SLC/IW, S2 L1C)",
            format="SLC / GRD / L1C / ...",
        ),
        # Platform fields (will be remapped through prip_map_mission where needed)
        "platform": QueryableField(
            title="platform",
            type="StringAttribute",
            description="Platform serial id (e.g., A/B/C/D)",
            format="A / B / C / D",
        ),
        "constellation": QueryableField(
            title="constellation",
            type="StringAttribute",
            description="Platform short name (e.g., SENTINEL-1)",
            format="SENTINEL-1 / SENTINEL-2 / ...",
        ),
        # Instrument mode (PRIP requires `sar:instrument_mode` for S1)
        "sar:instrument_mode": QueryableField(
            title="sar:instrument_mode",
            type="StringAttribute",
            description="Instrument mode (SAR) derived from PRIP product type (e.g., IW/EW/SM)",
            format="IW / EW / SM / ...",
        ),
        "file:size": QueryableField(
            title="file:size",
            type="Integer",
            description="Product size in bytes",
            format="12345678",
        ),
    }


# ----------------------
# Platform mapping utilities
# ----------------------
def prip_map_mission(platform: str | None, constellation: str | None) -> tuple[str | None, str | None]:
    """Map free-form STAC platform/constellation inputs to normalized values.

    Example:
        input ("sentinel-1a", "sentinel-1") → ("A", "sentinel-1")
        input (None, "sentinel-5P") → (None, "sentinel-5p")
    """
    if not (constellation or platform):
        return None, None

    if constellation:
        constellation = constellation.lower()  # type: ignore

    for sat in map_stac_platform().get("satellites", []):
        for sat_name, info in sat.items():
            if platform and info.get("serialid") == platform:
                return info.get("serialid"), info.get("constellation")
            if constellation and sat_name.lower() == constellation:
                return info.get("serialid"), info.get("constellation")

    return platform, constellation


def prip_reverse_map_mission(platform: str | None, constellation: str | None) -> tuple[str | None, str | None]:
    """Function used to re-map platform and constellation based on satellite value."""
    if not (constellation or platform):
        return None, None

    if constellation:
        constellation = constellation.lower()  # type: ignore

    for satellite in map_stac_platform().get("satellites", []):
        for sat_name, info in satellite.items():
            # Check for matching serialid and constellation
            if info.get("serialid") == platform and info.get("constellation", "").lower() == (constellation or ""):
                return sat_name, info.get("constellation")

    return platform, constellation


def prepare_collection(collection: stac_pydantic.ItemCollection) -> stac_pydantic.ItemCollection:
    """Used to create a more complex mapping on platform/constallation from odata to stac."""
    for feature in collection.features:
        feature.properties.platform, feature.properties.constellation = prip_reverse_map_mission(
            getattr(feature.properties, "platform", None),
            getattr(feature.properties, "constellation", None),
        )
    return collection
