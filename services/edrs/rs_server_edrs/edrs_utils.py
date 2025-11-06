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

from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Optional
import os
import os.path as osp
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



def build_stac_item_from_channel(client, channel_dir: str, files: list, collection_id: str, center: str) -> dict:
    """
    Build a minimal STAC Item for one (session x channel) using:
      - DSIB from the channel (prefer the locally downloaded file; fall back to client.read_file)
      - the 'files' list returned by client.walk(channel_dir)
      - absolute FTP paths from 'files[*]["path"]' for assets (DSDBs)
    Assumptions:
      - 'files' contains entries like {"path": "...", "type": "file"|"dir", "size": int|None}
      - The DSIB filename matches '*_DSIB.xml'
      - DSDB filenames match '*_DSDB_*.raw'
    """

    import re
    from pathlib import Path
    import xml.etree.ElementTree as ET

    # -------------------------------
    # 1) Locate DSIB entry in the channel
    # -------------------------------
    dsib_entry = next((f for f in files
                       if f.get("type") == "file" and str(f.get("path", "")).lower().endswith("_dsib.xml")), None)
    if not dsib_entry:
        raise RuntimeError("DSIB file not found in channel listing.")

    dsib_basename = Path(dsib_entry["path"]).name
    dsib_local = Path.cwd() / dsib_basename

    # -------------------------------
    # 2) Read DSIB bytes (prefer local downloaded copy; fallback to client.read_file)
    # -------------------------------
    if dsib_local.exists():
        dsib_bytes = dsib_local.read_bytes()
    else:
        # client.read_file is expected to return a dict; try common payload keys
        payload = client.read_file(dsib_entry["path"])
        if not isinstance(payload, dict):
            raise RuntimeError("client.read_file() did not return a dict.")
        dsib_bytes = (payload.get("content") or payload.get("bytes") or
                      payload.get("body") or payload.get("raw") or payload.get("data"))
        if isinstance(dsib_bytes, str):
            dsib_bytes = dsib_bytes.encode("utf-8")
        if not dsib_bytes:
            raise RuntimeError("Could not extract bytes from client.read_file() payload.")

    # -------------------------------
    # 3) Parse DSIB (robust to small tag name variations)
    # -------------------------------
    def _txt(el, default=""):
        return el.text.strip() if (el is not None and el.text) else default

    root = ET.fromstring(dsib_bytes)

    # Header block (try several common tag names)
    header = root.find("Header") or root.find("DSIB_Header") or root.find("DsibHeader")
    acq = (root.find("Acquisition_Info") or root.find("AcquisitionInfo") or
           root.find("Acquisition") or root.find("AcqInfo"))

    # Extract times (ISO 8601 expected)
    start_time = _txt(acq.find("Start_Time") if acq is not None else None)
    end_time = _txt(acq.find("End_Time") if acq is not None else None)

    # Satellite and basic identifiers (try header first; fallback to path-based parsing)
    satellite = _txt(header.find("Satellite") if header is not None else None)

    dcsu = _txt(header.find("DCSU_Number") if header is not None else None)
    session_id = _txt(header.find("Session_ID") if header is not None else None)
    channel_str = _txt(header.find("Channel") if header is not None else None)

    # If the header did not contain everything, use the DSIB filename
    # Pattern example: DCS_01_202501270945000000112233_ch1_DSIB.xml
    m = re.match(r"^DCS_(?P<dcsu>\d{2})_(?P<session>\d+)_ch(?P<ch>[12])_DSIB\.xml$", dsib_basename)
    if m:
        dcsu = dcsu or m.group("dcsu")
        session_id = session_id or m.group("session")
        channel_str = channel_str or m.group("ch")

    # Infer satellite from the absolute path if missing (e.g. /NOMINAL/S1A/.../ch_1/...)
    if not satellite:
        path_parts = [p for p in str(dsib_entry["path"]).split("/") if p]
        # Typical indices: ["NOMINAL", "S1A", "DCS_..._dat", "ch_1", "..."]
        if len(path_parts) >= 2:
            # If first element is NOMINAL, second is the satellite; else use the first
            satellite = path_parts[1] if path_parts[0].upper() == "NOMINAL" else path_parts[0]

    # Normalize types
    channel = int(channel_str) if channel_str else None

    # -------------------------------
    # 4) Build assets from DSDB files:
    #    - Prefer DSDB list in DSIB (if present)
    #    - Otherwise, take all files ending with '_DSDB_*.raw' from 'files'
    # -------------------------------
    # Index channel files by basename for quick lookup (to get size + absolute href)
    by_basename = {}
    for e in files:
        if e.get("type") == "file":
            by_basename[Path(e["path"]).name] = e

    # Try to read DSDB list from DSIB
    dsdb_nodes_parent = (root.find("Files") or root.find("DSDB_Files") or root.find("DsdbFiles"))
    dsib_dsdb_names = []
    if dsdb_nodes_parent is not None:
        for d in (dsdb_nodes_parent.findall("DSDB_File") or dsdb_nodes_parent.findall("File") or []):
            name = _txt(d.find("File_Name")) or _txt(d.find("Name"))
            if name:
                dsib_dsdb_names.append(name)

    assets = {}
    def _add_asset_from_entry(entry):
        bn = Path(entry["path"]).name
        assets[bn] = {
            "href": entry["path"],            # absolute FTP path from walk()
            "title": bn,
            "roles": ["cadu"],
            "file:size": entry.get("size"),
        }

    if dsib_dsdb_names:
        for name in dsib_dsdb_names:
            entry = by_basename.get(name)
            if entry:
                _add_asset_from_entry(entry)
            else:
                # Fallback: construct an absolute-ish href from channel_dir + name (keeps staging working)
                href = (channel_dir.rstrip("/") + "/" + name) if channel_dir else name
                assets[name] = {
                    "href": href,
                    "title": name,
                    "roles": ["cadu"],
                    # no size info from walk(); DSIB might have it but tag names vary—omit if unknown
                }
    else:
        # No explicit DSDB list in DSIB → use what we see in the channel listing
        for e in files:
            if e.get("type") == "file":
                bn = Path(e["path"]).name
                if "_DSDB_" in bn and bn.lower().endswith(".raw"):
                    _add_asset_from_entry(e)

    if not assets:
        raise RuntimeError("No DSDB assets found to include in STAC item.")

    # -------------------------------
    # 5) Compose minimal STAC Item
    # -------------------------------
    if not (dcsu and session_id and channel):
        raise RuntimeError("Missing identifiers (dcsu/session_id/channel) parsed from DSIB.")

    item_id = f"DCS_{dcsu}_{session_id}_ch{channel}"

    stac_item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/timestamps/v1.2.0/schema.json"
        ],
        "id": item_id,
        "collection": collection_id,
        "geometry": None,                      # no spatial footprint for raw CADU sessions
        "bbox": [-180, -90, 180, 90],          # neutral global bbox (can be omitted if undesired)
        "properties": {
            "datetime": start_time or None,    # STAC requires a single datetime; DSIB Start_Time expected
            "start_datetime": start_time or None,
            "end_datetime": end_time or None,
            "edrs:center": center,             # "pedc" | "bedc"
            "edrs:session_id": session_id,
            "edrs:channel": channel,           # 1 or 2
            "edrs:dcsu": dcsu,                 # "01" | "02" | ...
            "satellite": satellite,            # e.g., "S1A"
        },
        "assets": assets,
        "links": [],
    }

    return stac_item
