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

import copy
import json
import os
import os.path as osp
import re
from datetime import datetime as DateTime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fastapi import Request
from rs_server_common.utils.utils import map_stac_platform, odata_to_stac
from rs_server_common.utils.logging import Logging
from stac_pydantic import Item
from stac_pydantic import ItemCollection as StacItemCollection
from stac_pydantic.links import Link, Links
from stac_pydantic.shared import Asset

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
    """Return the cached STAC template used for session items."""
    return json.loads((EDRS_CONFIG / "edrs_session_STAC_template.json").read_text(encoding="utf-8"))


@lru_cache
def edrs_sessions_stac_mapper() -> dict:
    """Return the cached mapper between OData fields and STAC item properties."""
    return json.loads((EDRS_CONFIG / "edrs_sessions_stac_mapper.json").read_text(encoding="utf-8"))


@lru_cache
def edrs_stac_mapper() -> dict:
    """Return the cached mapper for asset-specific STAC properties."""
    return json.loads((EDRS_CONFIG / "edrs_asset_stac_mapper.json").read_text(encoding="utf-8"))


def platform_constellation_from_code(code: str) -> tuple[str | None, str | None]:
    """Return (platform, constellation) that matches the short satellite code."""
    # code ex.: "S1A", "S1C", "S2B" => returns satellites and constellation
    cfg = map_stac_platform()
    for sat in cfg["satellites"]:
        for plat, info in sat.items():
            if info.get("code") == code:
                return plat, info.get("constellation")
    return None, None


def iso(s: str | None) -> str | None:
    """Convert a datetime string to ISO-8601 with a trailing Z when relevant."""
    if not s:
        return None
    # normalize "2024-04-10T08:37:00Z" -> ISO with 'Z'
    return s.replace("+00:00", "Z")


def parse_dsib_dict(dsib: dict) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Extract the start/stop/creation timestamps stored in a DSIB document."""
    block = dsib.get("DCSU_Session_Information_Block") or {}
    start = block.get("time_start") or block.get("start_time") or block.get("start_datetime")
    stop = block.get("time_stop") or block.get("stop_time") or block.get("end_datetime")
    created = block.get("time_created") or block.get("created")
    finished = block.get("time_finished") or block.get("finished")

    # fallbacks consistent with how STAC Item is built
    if not created:
        created = finished or stop or start
    if not finished:
        finished = created or stop or start

    return None, iso(start), iso(stop), iso(created), iso(finished)


def collect_session_stats(client, sat: str, session_id: str) -> tuple[dict, list[dict]]:
    """Returns (session_odata, assets_products)."""
    ch_entries = client.walk(f"{sat}/{session_id}") or []
    channel_dirs = [
        e["path"] for e in ch_entries if e.get("type") == "dir" and re.search(r"/ch_\d+$", e.get("path", ""))
    ]

    starts, stops, gens = [], [], []
    assets_products: list[dict] = []
    platform_name, constellation = platform_constellation_from_code(sat)

    for ch_dir in channel_dirs:
        ch_name = ch_dir.rsplit("/", 1)[-1]  # ch_1
        ch_num = int(ch_name.split("_")[1]) if "_" in ch_name else None

        files = client.walk(f"{sat}/{session_id}/{ch_name}") or []
        # DSIB
        dsib_entry = next(
            (f for f in files if f.get("type") == "file" and f.get("path", "").lower().endswith("_dsib.xml")),
            None,
        )
        dsib_dict = None
        if dsib_entry:
            dsib_dict = client.read_file(dsib_entry["path"])
        # time din DSIB
        if dsib_dict:
            _, start, stop, created, _ = parse_dsib_dict(dsib_dict)
            if start:
                starts.append(start)
            if stop:
                stops.append(stop)
            if created:
                gens.append(created)

        # assets din walk (.raw)
        for f in files:
            p = f.get("path", "")
            if f.get("type") == "file" and p.lower().endswith(".raw"):
                assets_products.append(
                    {
                        "SessionId": session_id.removesuffix("_dat"),
                        "File_Name": Path(p).name,
                        "Size_Bytes": int(f.get("size") or 0),
                        "href": p,  # absolut ftp
                        "Channel": ch_num,
                        "Created": gens[-1] if gens else None,
                        "Updated": gens[-1] if gens else None,
                    },
                )

    session_odata = {
        "SessionId": session_id.removesuffix("_dat"),
        "MinStart": min(starts) if starts else None,
        "MaxStop": max(stops) if stops else None,
        "MinCreated": min(gens) if gens else None,
        "MaxFinished": max(gens) if gens else None,  # fallback to Generation_Time
        "Platform": platform_name,
        "Constellation": constellation,
    }
    return session_odata, assets_products


def build_assets_list(files: list[dict], ch_name: str) -> list[tuple[str, dict]]:
    """Build the asset tuple list for a channel traversal."""
    m = re.fullmatch(r"ch_(\d+)", ch_name)
    channel = int(m.group(1)) if m else None

    assets: list[tuple[str, dict]] = []
    for f in files:
        p = f.get("path", "")
        if f.get("type") == "file" and p.lower().endswith(".raw"):
            fname = Path(p).name
            assets.append(
                (
                    fname,
                    {
                        "path": p,
                        "channel": channel,
                        "file:size": int(f.get("size") or 0),
                    },
                ),
            )
    return assets


def apply_asset_mapping_to_item(item: Item, asset_items: list[dict]) -> None:
    """Populate Item assets based on the configured mapper definition."""
    mapper = edrs_stac_mapper()
    key_field = mapper["id"]
    out_specs = {k: v for k, v in mapper.items() if k != "id"}

    for a in asset_items:
        key = a.get(key_field)
        if not key:
            continue
        out = {
            ok: (a.get(spec) if isinstance(spec, str) else spec)
            for ok, spec in out_specs.items()
            if not (isinstance(spec, str) and a.get(spec) is None)
        }
        item.assets[key] = Asset.model_validate(out)


def build_edrs_item_collection(
    client,
    satellites: list[str],
    collection_id: str,
    request: Request,
) -> dict[str, Any]:
    """Collect and convert EDRS FTP sessions into a STAC ItemCollection dict."""
    items: list[Item] = []

    service_base = str(request.url).split("/collections/", maxsplit=1)[0].rstrip("/")
    collection_href = f"{service_base}/collections/{collection_id}"
    root_href = f"{service_base}/"

    for sat in satellites:
        entries = client.walk(sat) or []

        # collect session directories
        session_dirs = [
            e["path"]
            for e in entries
            if e.get("type") == "dir" and re.fullmatch(rf"/NOMINAL/{re.escape(sat)}/DCS_\d+_\d+_dat", e.get("path", ""))
        ]

        for sess_path in session_dirs:
            session_id = Path(sess_path).name
            session, asset_products = collect_session_stats(client, sat, session_id)
            feature = odata_to_stac(
                copy.deepcopy(edrs_session_odata_to_stac_template()),
                session,
                edrs_sessions_stac_mapper(),
            )

            feature["collection"] = collection_id
            item = Item(**feature)

            apply_asset_mapping_to_item(item, asset_products)
            self_href = f"{collection_href}/items/{item.id}"
            item.links = Links(
                root=[
                    Link(rel="collection", type="application/json", href=collection_href),
                    Link(rel="parent", type="application/json", href=collection_href),
                    Link(rel="root", type="application/json", href=root_href),
                    Link(rel="self", type="application/geo+json", href=self_href),
                ],
            )
            items.append(item)

    ic_links = Links(
        root=[
            Link(rel="collection", type="application/json", href=collection_href),
            Link(rel="parent", type="application/json", href=collection_href),
            Link(rel="root", type="application/json", href=root_href),
            Link(rel="self", type="application/geo+json", href=str(request.url)),
        ],
    )

    return StacItemCollection(type="FeatureCollection", features=items, links=ic_links).to_dict()
