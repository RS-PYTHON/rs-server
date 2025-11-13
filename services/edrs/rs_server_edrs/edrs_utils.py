# Copyright 2025 CS Group
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
Module for interacting with EDRS system through a FastAPI APIRouter.
"""

import json
import os
import os.path as osp
from functools import lru_cache
from pathlib import Path

import yaml
from rs_server_common.utils.logging import Logging

EDRS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
EDRS_CONFIG_COLLECTIONS = EDRS_CONFIG / "edrs_collections.yaml"

logger = Logging.default(__name__)


@lru_cache
def edrs_read_conf() -> dict:
    """Used each time to read EDRS_COLLECTIONS_YAML config yaml."""
    edrs_cfg_path = os.environ.get("RSPY_EDRS_COLLECTIONS_CONFIG", str(EDRS_CONFIG_COLLECTIONS))
    with open(edrs_cfg_path, encoding="utf-8") as cfg:
        return yaml.safe_load(cfg) or {}


def edrs_select_config(configuration_id: str) -> dict | None:
    """Used to select a specific configuration from yaml file, returns None if not found."""
    return next(
        (item for item in edrs_read_conf()["collections"] if item["id"] == configuration_id),
        None,
    )


def select_config(configuration_id: str) -> dict | None:
    """Used to select a specific configuration from yaml file, returns None if not found."""
    return next(
        (item for item in edrs_read_conf()["collections"] if item["id"] == configuration_id),
        None,
    )


@lru_cache
def edrs_session_odata_to_stac_template() -> dict:
    return json.loads((EDRS_CONFIG / "edrs_session_STAC_template.json").read_text(encoding="utf-8"))


@lru_cache
def edrs_sessions_stac_mapper() -> dict:
    return json.loads((EDRS_CONFIG / "edrs_sessions_stac_mapper.json").read_text(encoding="utf-8"))


@lru_cache
def edrs_stac_mapper() -> dict:
    return json.loads((EDRS_CONFIG / "edrs_asset_stac_mapper.json").read_text(encoding="utf-8"))
