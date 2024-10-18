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
"""

import os
import os.path as osp
from functools import lru_cache
from pathlib import Path
from typing import Union

import yaml
from fastapi import HTTPException, status
from rs_server_common.stac_api_common import (
    RSPYQueryableField,
    generate_queryables,
    map_stac_platform,
)

ADGS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
search_yaml = ADGS_CONFIG / "adgs_search_config.yaml"


@lru_cache(maxsize=1)
def read_conf():
    """Used each time to read RSPY_ADGS_SEARCH_CONFIG config yaml."""
    adgs_search_config = os.environ.get("RSPY_ADGS_SEARCH_CONFIG", str(search_yaml.absolute()))
    with open(adgs_search_config, encoding="utf-8") as search_conf:
        config = yaml.safe_load(search_conf)
    return config


def select_config(configuration_id: str) -> dict | None:
    """Used to select a specific configuration from yaml file, returns None if not found."""
    return next(
        (item for item in read_conf()["collections"] if item["id"] == configuration_id),
        None,
    )


def serialize_adgs_asset(feature_collection, request):
    """Used to update adgs asset with propper href and format {asset_name: asset_body}."""
    for feature in feature_collection.features:
        feature.assets["file"].href = f"{request.url.scheme}://{request.url.netloc}/adgs/aux?name={feature.id}"
        feature.assets[feature.id] = feature.assets.pop("file")
    return feature_collection


def get_adgs_queryables() -> dict[str, RSPYQueryableField]:
    """Function to list all available queryables for CADIP session search."""
    return {
        "PublicationDate": RSPYQueryableField(
            title="PublicationDate",
            type="Interval",
            description="Session Publication Date",
            format="1940-03-10T12:00:00Z/2024-01-01T12:00:00Z",
        ),
        "processingDate": RSPYQueryableField(
            title="Processing Date",
            type="DateTimeOffset",
            description="Auxip processing date",
            format="2019-02-16T12:00:00.000Z",
        ),
        "platformSerialIdentifier": RSPYQueryableField(
            title="Platform Serial Identifier",
            type="StringAttribute",
            description="Mission identifier (A/B/C)",
            format="A / B / C",
        ),
        "platformShortName": RSPYQueryableField(
            title="Platform Short Name",
            type="StringAttribute",
            description="Platform Short name",
            format="SENTINEL-2 / SENTINEL-1",
        ),
        "constellation": RSPYQueryableField(
            title="constellation",
            type="StringAttribute",
            description="constellation name",
            format="SENTINEL-2 / SENTINEL-1",
        ),
    }


def auxip_map_mission(platform: str, constellation: str):
    """
    Custom function for ADGS, to read constellation mapper and return propper
    values for platform and serial.
    Eodag maps this values to platformShortName, platformSerialIdentifier

    Input: platform = sentinel-1a       Output: sentinel-1, A
    Input: platform = sentinel-5P       Output: sentinel-5p, None
    Input: constellation = sentinel-1   Output: sentinel-1, None
    """
    data = map_stac_platform()
    platform_short_name: Union[str, None] = None
    platform_serial_identifier: Union[str, None] = None
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Cannot map platform/constellation",
        ) from exc
    return platform_short_name, platform_serial_identifier


def generate_adgs_queryables(collection_id: str) -> dict[str, RSPYQueryableField]:
    """Function used to get available queryables based on a given collection."""
    config = select_config(collection_id)
    return generate_queryables(config, get_adgs_queryables)
