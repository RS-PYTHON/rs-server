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
Helpers for exposing EDRS sessions as STAC resources.
Load YAML configs, walk station directories, build Items/Collections, and apply
basic CQL2 filters for /items.
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
EDRS_SEARCH_CONFIG = EDRS_CONFIG / "edrs_search_config.yaml"

logger = Logging.default(__name__)


@lru_cache
def edrs_read_conf() -> dict:
    """Used each time to read the EDRS search config YAML."""
    config_path = os.environ.get("RSPY_EDRS_COLLECTIONS_CONFIG", str(EDRS_SEARCH_CONFIG))
    with open(config_path, encoding="utf-8") as config_file:
        return yaml.safe_load(config_file) or {}


def edrs_select_config(configuration_id: str) -> dict | None:
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
    platform_mapping = map_stac_platform()
    for satellite_entry in platform_mapping["satellites"]:
        for platform_key, platform_info in satellite_entry.items():
            if platform_info.get("code") == code:
                return platform_key, platform_info.get("constellation")
    return None, None


def iso(datetime_value: str | None) -> str | None:
    """Convert a datetime string to ISO-8601 with a trailing Z when relevant."""
    if not datetime_value:
        return None
    # normalize "2024-04-10T08:37:00Z" -> ISO with 'Z'
    return datetime_value.replace("+00:00", "Z")


def parse_dsib_dict(dsib: dict) -> tuple[str | None, str | None, str | None, str | None]:
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

    return iso(start), iso(stop), iso(created), iso(finished)


def collect_session_stats(
    client,
    satellite_code: str,
    session_id: str,
    station_name: str,
) -> tuple[dict, list[dict]]:
    """Collect session metadata and raw asset records for a given station session."""
    # Walk the session root to locate channel subfolders.
    ch_entries = client.walk(f"{satellite_code}/{session_id}") or []
    channel_dirs = [
        e["path"] for e in ch_entries if e.get("type") == "dir" and re.search(r"/ch_\d+$", e.get("path", ""))
    ]

    start_times: list[str] = []
    stop_times: list[str] = []
    generation_times: list[str] = []
    assets_products: list[dict] = []
    platform_name, constellation = platform_constellation_from_code(satellite_code)

    for channel_dir in channel_dirs:
        channel_name = channel_dir.rsplit("/", 1)[-1]  # ch_1
        channel_number = int(channel_name.split("_")[1]) if "_" in channel_name else None

        # Enumerate files for this channel and try to read the DSIB metadata.
        channel_entries = client.walk(f"{satellite_code}/{session_id}/{channel_name}") or []
        # Locate the DSIB manifest in this channel to extract timestamps.
        dsib_entry = next(
            (
                entry
                for entry in channel_entries
                if entry.get("type") == "file" and entry.get("path", "").lower().endswith("_dsib.xml")
            ),
            None,
        )
        dsib_dict = None
        if dsib_entry:
            dsib_dict = client.read_file(dsib_entry["path"])
        # Parse timing information from DSIB if available.
        if dsib_dict:
            start, stop, created, _ = parse_dsib_dict(dsib_dict)
            for value, target in (
                (start, start_times),
                (stop, stop_times),
                (created, generation_times),
            ):
                if value:
                    target.append(value)

        # Build asset entries for .raw files, carrying channel info and timestamps.
        latest_generation_time = next(reversed(generation_times), None)
        for entry in channel_entries:
            entry_path = entry.get("path", "")
            if entry.get("type") == "file" and entry_path.lower().endswith(".raw"):
                assets_products.append(
                    {
                        "SessionId": session_id.removesuffix("_dat"),
                        "File_Name": Path(entry_path).name,
                        "Size_Bytes": int(entry.get("size", 0)),
                        "href": f"ftps://{station_name}{entry_path}",
                        "Channel": channel_number,
                        "Created": latest_generation_time,
                        "Updated": latest_generation_time,
                    },
                )

    session_odata = {
        "SessionId": session_id.removesuffix("_dat"),
        "MinStart": min(start_times, default=None),
        "MaxStop": max(stop_times, default=None),
        "MinCreated": min(generation_times, default=None),
        "MaxFinished": max(generation_times, default=None),  # fallback to Generation_Time
        "Platform": platform_name,
        "Constellation": constellation,
    }
    return session_odata, assets_products


def apply_asset_mapping_to_item(item: Item, asset_items: list[dict]) -> None:
    """Populate Item assets based on the configured mapper definition."""
    mapper_definition = edrs_stac_mapper()
    key_field = mapper_definition["id"]
    output_specs = {k: v for k, v in mapper_definition.items() if k != "id"}

    for asset_entry in asset_items:
        key = asset_entry.get(key_field)
        if not key:
            continue
        asset_payload = {
            output_key: (asset_entry.get(mapping_spec) if isinstance(mapping_spec, str) else mapping_spec)
            for output_key, mapping_spec in output_specs.items()
            if not (isinstance(mapping_spec, str) and asset_entry.get(mapping_spec) is None)
        }
        item.assets[key] = Asset.model_validate(asset_payload)


def build_edrs_item_collection(
    client,
    satellites: list[str],
    collection_id: str,
    request: Request,
    station_name: str,
) -> dict[str, Any]:
    """
    Collect and convert EDRS FTP sessions into a STAC ItemCollection dict.

    Each satellite folder is walked, session dirs are converted to Items via the
    mapper templates, assets are attached, and STAC links are populated so the
    response matches the other STAC-driven station collections.
    """
    items: list[Item] = []

    service_base = str(request.url).split("/collections/", maxsplit=1)[0].rstrip("/")
    collection_href, root_href = (
        f"{service_base}/collections/{collection_id}",
        f"{service_base}/",
    )

    def is_session_dir(path_str: str, sat_code: str) -> bool:
        """Return True if the path matches /NOMINAL/<sat_code>/DCS_<num>_<num>_dat."""
        if not path_str or not path_str.startswith(f"/NOMINAL/{sat_code}/"):
            return False
        tail = Path(path_str).name
        parts = tail.split("_")
        return len(parts) == 4 and parts[0] == "DCS" and parts[3] == "dat"

    for satellite_code in satellites:
        session_dirs = [
            entry["path"]
            for entry in (client.walk(satellite_code) or [])
            if entry.get("type") == "dir" and is_session_dir(entry.get("path", ""), satellite_code)
        ]

        for session_path in session_dirs:
            session_id = Path(session_path).name
            session, asset_products = collect_session_stats(client, satellite_code, session_id, station_name)
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


def parse_iso_value(value: str | None):
    """Parse an ISO datetime string (or date) into a datetime, tolerant to Z suffix."""
    if not value:
        return None
    normalized_value = str(value).strip()
    if normalized_value.endswith("Z"):
        normalized_value = normalized_value[:-1] + "+00:00"
    try:
        return DateTime.fromisoformat(normalized_value)
    except Exception:  # pylint: disable=broad-exception-caught
        try:
            return DateTime.fromisoformat(normalized_value + "T00:00:00+00:00")
        except Exception:  # pylint: disable=broad-exception-caught
            return None


TEMPORAL_KEYS = {"datetime", "start_datetime", "end_datetime", "published"}


def normalize_features(features: list) -> list[dict]:
    """Convert mixed feature representations (pystac/stac-pydantic/dicts) into plain dicts."""
    normalized = []
    for feature_obj in features or []:
        if isinstance(feature_obj, dict):
            normalized.append(feature_obj)
        elif hasattr(feature_obj, "model_dump"):
            normalized.append(feature_obj.model_dump())
        elif hasattr(feature_obj, "to_dict"):
            normalized.append(feature_obj.to_dict())
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
    Supports CQL2-text and CQL2-JSON equality filters plus datetime interval,
    then delegates sorting/pagination to MockPgstac to mimic STAC /items paging.
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

    query_start, query_end = parse_datetime_interval(datetime_expr)

    def match_props(feature: dict) -> bool:
        properties = feature.get("properties", {})
        for field_name, expected_value in conditions:
            if field_name == "id":
                if str(feature.get("id", "")) != str(expected_value):
                    return False
            else:
                property_value = properties.get(field_name, "")
                if field_name in TEMPORAL_KEYS:
                    left = parse_iso_value(property_value)
                    right = parse_iso_value(expected_value)
                    if left and right:
                        if left != right:
                            return False
                    else:
                        if str(property_value) != str(expected_value):
                            return False
                else:
                    if str(property_value) != str(expected_value):
                        return False
        return True

    def match_datetime(feature: dict) -> bool:
        properties = feature.get("properties", {})
        item_start = parse_iso_value(properties.get("start_datetime") or properties.get("datetime"))
        item_end = parse_iso_value(properties.get("end_datetime") or properties.get("datetime"))
        return intersects_time(item_start, item_end, query_start, query_end)

    filtered_features = [feature for feature in features if match_props(feature) and match_datetime(feature)]

    item_collection_model = RspyItemCollection.model_validate(
        {
            "type": "FeatureCollection",
            "features": filtered_features,
        },
    )

    paging_context = SimpleNamespace(sortby=str(sort_by_expr), limit=limit_value, page=page_value)
    return MockPgstac.paginate(paging_context, item_collection_model)


def parse_cql2_text(expr: str, add_condition):
    """Parse CQL2 text expression (eq + AND) into conditions via callback."""
    parts = re.split(r"\bAND\b", expr, flags=re.IGNORECASE)
    for raw_segment in parts:
        segment = raw_segment.strip()
        if not segment:
            continue
        if "=" not in segment:
            raise ValueError(f"Invalid filter condition: {segment!r}")
        left, right = segment.split("=", 1)
        left, right = left.strip(), right.strip()
        if not re.fullmatch(r"[\w:.\-]+", left):
            raise ValueError(f"Invalid filter condition: {segment!r}")
        if right.startswith(("'", '"')) and right.endswith(("'", '"')) and len(right) >= 2:
            right = right[1:-1]
        add_condition(left, right)


def parse_cql2_json_node(node, add_condition):
    """Walk a CQL2 JSON tree (eq/and) and invoke add_condition on equality ops."""
    if not isinstance(node, dict):
        raise ValueError("Invalid CQL2-JSON filter")
    op = str(node.get("op", "")).lower()
    args = node.get("args", [])
    if op == "and":
        for argument in args:
            parse_cql2_json_node(argument, add_condition)
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


def parse_datetime_interval(expression: str | None):
    """
    Parse a datetime or interval string into a (start, end) tuple (closed range).

    - None -> (None, None)
    - Single datetime string -> (instant_start, instant_end)
    - Interval "start/end" -> (start_dt_or_None, end_dt_or_None), with ".." treated as open bound -> None.
    """

    def parse_iso(value: str):
        """Return a datetime from a single ISO string, tolerant to trailing 'Z'; raise if empty."""
        normalized_value = str(value).strip()
        if normalized_value.endswith("Z"):
            normalized_value = normalized_value[:-1] + "+00:00"
        try:
            return DateTime.fromisoformat(normalized_value)
        except Exception:  # pylint: disable=broad-exception-caught
            try:
                return DateTime.fromisoformat(normalized_value + "T00:00:00+00:00")
            except Exception:  # pylint: disable=broad-exception-caught
                return None

    if not expression:
        return None, None
    normalized_expr = str(expression).strip()
    if "/" in normalized_expr:
        start_expr, end_expr = normalized_expr.split("/", 1)
        return (
            parse_iso(start_expr) if start_expr and start_expr != ".." else None,
            parse_iso(end_expr) if end_expr and end_expr != ".." else None,
        )
    # Single instant: treat it as a closed interval at that instant.
    moment = parse_iso(normalized_expr)
    return moment, moment


def intersects_time(
    item_start: DateTime | None,
    item_end: DateTime | None,
    query_start: DateTime | None,
    query_end: DateTime | None,
) -> bool:
    """Return True if the item interval intersects the query interval."""
    if query_start is None and query_end is None:
        return True
    if item_start is None and item_end is None:
        return True
    range_start = item_start or item_end
    range_end = item_end or item_start
    result = True
    # At this point range_start/range_end are non-None; only mypy complains about optional comparisons.
    if query_start and query_end:
        result = (range_start <= query_end) and (range_end >= query_start)  # type: ignore[operator]
    elif query_start:
        result = range_end >= query_start  # type: ignore[operator]
    elif query_end:
        result = range_start <= query_end  # type: ignore[operator]
    return result
