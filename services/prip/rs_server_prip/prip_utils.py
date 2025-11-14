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
Module for interacting with PRIP system through a FastAPI APIRouter.
"""
# pylint: disable=duplicate-code
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
from rs_server_common.utils.utils import reverse_adgs_prip_map_mission

PRIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
search_yaml = PRIP_CONFIG / "prip_search_config.yaml"


# ----------------------
# Config loaders
# ----------------------
@lru_cache
def read_conf():
    """Used each time to read RSPY_PRIP_SEARCH_CONFIG config yaml."""
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
        prip_id = feature.properties.dict().get("prip:id") or feature.id
        # Find matching product by id
        matched = next((p for p in products if p.properties.get("id") == prip_id), None)  # type: ignore[attr-defined]
        if not matched:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unable to map product for feature {feature.id}",
            )
        # href = matched.get("properties", {}).get("href")
        href = matched.properties.get("href")  # type: ignore[attr-defined]
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

        # Merge any existing roles with required ones and de-duplicate
        existing_roles = list(asset.roles or [])
        asset.roles = list(dict.fromkeys(existing_roles + ["data", "metadata"]))
        # Normalize item id (drop extension if any)
        feature.id = new_key

    return feature_collection


def prepare_collection(collection: stac_pydantic.ItemCollection) -> stac_pydantic.ItemCollection:
    """Used to create a more complex mapping on platform/constallation from odata to stac."""
    for feature in collection.features:
        feature.properties.platform, feature.properties.constellation = reverse_adgs_prip_map_mission(
            feature.properties.platform,
            feature.properties.constellation,
        )
    return collection
