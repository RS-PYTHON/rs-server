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
from types import SimpleNamespace
from typing import Any

import yaml
from fastapi import Request
from rs_server_common.rspy_models import ItemCollection as RspyItemCollection
from rs_server_common.stac_api_common import MockPgstac, check_input_type
from rs_server_common.utils.cql2_filter_extension import process_filter_extensions
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import map_stac_platform, odata_to_stac
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
    collection_href, root_href = (
        f"{service_base}/collections/{collection_id}",
        f"{service_base}/",
    )

    for sat in satellites:
        session_dirs = [
            e["path"]
            for e in (client.walk(sat) or [])
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

            item = Item(**{**feature, "collection": collection_id})

            apply_asset_mapping_to_item(item, asset_products)
            item.links = Links(
                root=[
                    Link(rel="collection", type="application/json", href=collection_href),
                    Link(rel="parent", type="application/json", href=collection_href),
                    Link(rel="root", type="application/json", href=root_href),
                    Link(
                        rel="self",
                        type="application/geo+json",
                        href=f"{collection_href}/items/{item.id}",
                    ),
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


####################################
# Filtering / pagination utilities #
####################################


def normalize_features(features: list) -> list[dict]:
    """Convert mixed feature representations into plain dicts."""
    normalized = []
    for f in features or []:
        if isinstance(f, dict):
            normalized.append(f)
        elif hasattr(f, "model_dump"):
            normalized.append(f.model_dump())
        elif hasattr(f, "to_dict"):
            normalized.append(f.to_dict())
        else:
            raise ValueError("Invalid feature type in collection")
    return normalized


def filter_and_paginate_features(
    features: list[dict],
    query_params,
    queryables_raw: dict,
    sortby_default: str = "-datetime",
    limit_default: int = 1000,
    page_default: int = 1,
) -> dict:
    """
    Apply property/datetime filters + pagination/sort to a list of feature dicts.
    Returns a paginated dict via MockPgstac.paginate.
    """
    sort_by_expr = query_params.get("sortby") or sortby_default
    limit_value = int(query_params.get("limit") or limit_default)
    page_value = int(query_params.get("page") or page_default)
    filter_expr = query_params.get("filter")
    filter_lang_value = (query_params.get("filter-lang") or "cql2-text").lower()
    datetime_expr = query_params.get("datetime")

    allowed_props = set(queryables_raw.keys()) | {"id"}

    field_info = {
        k: (
            v
            if hasattr(v, "type")
            else (
                SimpleNamespace(type=v["type"])
                if isinstance(v, dict) and "type" in v
                else SimpleNamespace(type="string")
            )
        )
        for k, v in queryables_raw.items()
    }

    conditions = []

    def add_condition(prop_name: str, value):
        key = prop_name
        if key.startswith("properties."):
            key = key.split(".", 1)[1]
        if key not in allowed_props:
            raise ValueError(f"Invalid query filter property: {prop_name!r}")
        if key != "id":
            check_input_type(field_info, key, value)
        conditions.append((key, str(value)))

    if filter_expr:
        if filter_lang_value in {"cql2-json", "application/cql+json"}:
            node = filter_expr
            if isinstance(node, str):
                node = json.loads(node)
            parse_cql2_json_node(process_filter_extensions(node), add_condition)
        elif filter_lang_value == "cql2-text":
            parse_cql2_text(str(filter_expr), add_condition)
        else:
            raise ValueError(f"Unsupported filter-lang: {filter_lang_value}")

    q_start, q_end = parse_datetime_interval(datetime_expr)

    def parse_iso(val: str | None):
        if not val:
            return None
        s = str(val).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return DateTime.fromisoformat(s)
        except Exception:  # pylint: disable=broad-exception-caught
            try:
                return DateTime.fromisoformat(s + "T00:00:00+00:00")
            except Exception:  # pylint: disable=broad-exception-caught
                return None

    def match_props(feature: dict) -> bool:
        for k, v in conditions:
            if k == "id":
                if str(feature.get("id", "")) != str(v):
                    return False
            else:
                if str(feature.get("properties", {}).get(k, "")) != str(v):
                    return False
        return True

    def match_datetime(feature: dict) -> bool:
        props = feature.get("properties", {})
        item_start = parse_iso(props.get("start_datetime") or props.get("datetime"))
        item_end = parse_iso(props.get("end_datetime") or props.get("datetime"))
        return intersects_time(item_start, item_end, q_start, q_end)

    filtered_features = [f for f in features if match_props(f) and match_datetime(f)]

    item_collection_model = RspyItemCollection.model_validate(
        {
            "type": "FeatureCollection",
            "features": filtered_features,
        },
    )

    paging_ctx = SimpleNamespace(sortby=str(sort_by_expr), limit=limit_value, page=page_value)
    return MockPgstac.paginate(paging_ctx, item_collection_model)


def parse_cql2_text(expr: str, add_condition):
    """Parse CQL2 text expression into conditions via callback."""
    parts = re.split(r"\\bAND\\b", expr, flags=re.IGNORECASE)
    for raw in parts:
        segment = raw.strip()
        if not segment:
            continue
        m = re.match(r"^([\\w\\:\\.\\-]+)\\s*=\\s*(.+)$", segment)
        if not m:
            raise ValueError(f"Invalid filter condition: {segment!r}")
        left, right = m.group(1).strip(), m.group(2).strip()
        if right.startswith(("'", '"')) and right.endswith(("'", '"')) and len(right) >= 2:
            right = right[1:-1]
        add_condition(left, right)


def parse_cql2_json_node(node, add_condition):
    """Walk a CQL2 JSON tree and invoke add_condition on equality ops."""
    if not isinstance(node, dict):
        raise ValueError("Invalid CQL2-JSON filter")
    op = str(node.get("op", "")).lower()
    args = node.get("args", [])
    if op == "and":
        for a in args:
            parse_cql2_json_node(a, add_condition)
    elif op in {"=", "eq"} and len(args) == 2:
        left, right = args[0], args[1]
        if isinstance(left, dict) and "property" in left:
            prop_name = left["property"]
        elif isinstance(left, str):
            prop_name = left
        else:
            raise ValueError("Invalid CQL2-JSON left operand")
        if isinstance(right, dict) and "literal" in right:
            value = right["literal"]
        else:
            value = right
        add_condition(prop_name, value)
    else:
        raise ValueError(f"Unsupported CQL2-JSON operator: {op}")


def parse_datetime_interval(expr: str | None):
    """Parse a datetime or interval string into (start, end) datetimes."""

    def parse_iso(val: str | None):
        if not val:
            return None
        s = str(val).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return DateTime.fromisoformat(s)
        except Exception:  # pylint: disable=broad-exception-caught
            try:
                return DateTime.fromisoformat(s + "T00:00:00+00:00")
            except Exception:  # pylint: disable=broad-exception-caught
                return None

    if not expr:
        return None, None
    s = str(expr).strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return (parse_iso(a) if a and a != ".." else None), (parse_iso(b) if b and b != ".." else None)
    t = parse_iso(s)
    return t, t


def intersects_time(item_start, item_end, q_start, q_end):
    """Return True if item time interval intersects query interval."""
    if q_start is None and q_end is None:
        return True
    if item_start is None and item_end is None:
        return True
    s = item_start or item_end
    e = item_end or item_start
    if s is None and e is None:
        return True
    result = True
    if q_start and q_end:
        result = (s <= q_end) and (e >= q_start)
    elif q_start:
        result = e >= q_start
    elif q_end:
        result = s <= q_end
    return result
