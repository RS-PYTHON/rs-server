# Copyright 2023-2025 Airbus, CS Group
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
"""

import json
import os
import os.path as osp
import re
from functools import lru_cache
from pathlib import Path

import stac_pydantic
import yaml
from fastapi import HTTPException, status
from rs_server_common.utils.utils import reverse_adgs_prip_map_mission

ADGS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
search_yaml = ADGS_CONFIG / "adgs_search_config.yaml"


@lru_cache
def read_conf():
    """Used each time to read RSPY_ADGS_SEARCH_CONFIG config yaml."""
    adgs_search_config = os.environ.get("RSPY_ADGS_SEARCH_CONFIG", str(search_yaml.absolute()))
    with open(adgs_search_config, encoding="utf-8") as search_conf:
        config = yaml.safe_load(search_conf)
    return config  # WARNING: if the caller wants to modify this cached object, it must deepcopy it first


@lru_cache
def auxip_odata_to_stac_template():
    """Used each time to read the ODataToSTAC_template json template."""
    with open(ADGS_CONFIG / "ODataToSTAC_template.json", encoding="utf-8") as mapper:
        config = json.loads(mapper.read())
    return config  # WARNING: if the caller wants to modify this cached object, he must deepcopy it first


@lru_cache
def auxip_stac_mapper():
    """Used each time to read the adgs_stac_mapper config yaml."""
    with open(ADGS_CONFIG / "adgs_stac_mapper.json", encoding="utf-8") as stac_map:
        config = json.loads(stac_map.read())
    return config  # WARNING: if the caller wants to modify this cached object, it must deepcopy it first


def select_config(configuration_id: str) -> dict | None:
    """Used to select a specific configuration from yaml file, returns None if not found."""
    return next(
        (item for item in read_conf()["collections"] if item["id"] == configuration_id),
        None,
    )


def _normalize_external_ids(value: str | list[str]) -> list[str] | None:
    """Normalize externalIds search values for the auxip scheme."""
    tokens: list[str] = []
    scheme_only_auxip = False
    scheme_only_other = False
    values = value if isinstance(value, list) else [value]
    for raw in values:
        if raw is None:
            continue
        raw_str = str(raw)
        parts = [s.strip() for s in raw_str.split(",")] if "," in raw_str else [raw_str.strip()]
        for part in parts:
            if not part:
                continue
            if ":" in part:
                scheme, val = part.split(":", 1)
                scheme = scheme.strip()
                val = val.strip()
                if not val:
                    if scheme == "auxip":
                        scheme_only_auxip = True
                    else:
                        scheme_only_other = True
                    continue
                if scheme != "auxip":
                    continue
                tokens.append(val)
            else:
                tokens.append(part)
    if tokens:
        return tokens
    if scheme_only_auxip and not scheme_only_other:
        return None
    if scheme_only_auxip and scheme_only_other:
        return None
    return []


def stac_to_odata(stac_params: dict) -> dict:
    """Convert a parameter directory from STAC keys to OData keys. Return the new directory."""
    params = dict(stac_params)
    if "externalIds" in params:
        normalized = _normalize_external_ids(params.pop("externalIds"))
        if normalized is None:
            pass
        elif not normalized:
            params["externalIds"] = "__no_match__"
        elif len(normalized) == 1:
            params["externalIds"] = normalized[0]
        else:
            params["externalIdss"] = normalized
    return {auxip_stac_mapper().get(stac_key, stac_key): value for stac_key, value in params.items()}


def serialize_adgs_asset(feature_collection, products):
    """Used to update adgs asset with proper href and format {asset_name: asset_body}."""
    for feature in feature_collection.features:
        external_ids = feature.properties.dict().get("externalIds") or []
        auxip_id = next(
            (
                entry.get("value")
                for entry in external_ids
                if isinstance(entry, dict) and entry.get("scheme") == "auxip"
            ),
            None,
        )
        if not auxip_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Missing externalIds for feature {feature.id}",
            )
        # Find matching product by id and update feature href
        try:
            matched_product = next((p for p in products if p.properties["id"] == auxip_id), None)
        except StopIteration as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unable to map {feature.id}") from exc
        if matched_product:
            feature.assets["file"].href = re.sub(r"\([^\)]*\)", f"({auxip_id})", matched_product.properties["href"])
        # Rename "file" asset to feature.id
        feature.assets[feature.id] = feature.assets.pop("file")
        feature.id = feature.id.rsplit(".", 1)[0]  # remove extension if any
    return feature_collection


def prepare_collection(collection: stac_pydantic.ItemCollection) -> stac_pydantic.ItemCollection:
    """Used to create a more complex mapping on platform/constallation from odata to stac."""
    for feature in collection.features:
        feature.properties.platform, feature.properties.constellation = reverse_adgs_prip_map_mission(
            feature.properties.platform,
            feature.properties.constellation,
        )
    return collection
