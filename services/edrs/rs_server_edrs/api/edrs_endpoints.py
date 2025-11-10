from typing import Optional, Literal, Annotated
from fastapi import APIRouter, Request, HTTPException, status
from fastapi import Path as FPath
from fastapi.responses import RedirectResponse
import stac_pydantic
from stac_pydantic import Item, ItemCollection
from stac_pydantic.shared import Asset

from pathlib import Path

from xml.etree import ElementTree as ET

import re

from rs_server_common.authentication import authentication
from rs_server_common.stac_api_common import MockPgstac, handle_exceptions
from rs_server_common.utils.logging import Logging

from rs_server_edrs.edrs_utils import edrs_read_conf, edrs_select_config, select_config
from rs_server_edrs.edrs_client import EDRSConnector, load_station_config, EDRS_STATIONS_CONFIG

logger = Logging.default(__name__)
router = APIRouter()

def _dummy_Item(collection: str, item_id: str, assets_list: list[tuple[str, dict]]) -> Item:
    assets: dict[str, dict] = {}
    for fname, meta in (assets_list or []):
        assets[fname] = {
            "href": meta["path"],
            "title": fname,
            "roles": ["cadu"],
            "channel": meta.get("channel"),
            "created":"",
            "updated":"",
            "file:size": meta.get("file:size", 0),
        }

    item = Item(
        id=item_id,
        type="Feature",
        stac_version="1.0.0",
        collection=collection,
        properties={
            "datetime": "2025-10-10T18:37:22.000Z",
            "platform": "sentinel-3b",
            "constellation": "sentinel-3",
        },
        geometry=None,
        assets=assets,
        links=[],
    )
    return item

def _read_text(meta: dict) -> Optional[str]:
    x = meta.get("content") or meta.get("body") or meta.get("data")
    if x is None:
        return None
    if isinstance(x, (bytes, bytearray)):
        try:
            return x.decode("utf-8")
        except Exception:
            return x.decode("latin-1", errors="ignore")
    return str(x)


def _constellation_platform(sat: str) -> tuple[str, str]:
    s = sat.upper()
    if s.startswith("S1"):
        return "sentinel-1", f"sentinel-1{s[-1].lower()}"
    if s.startswith("S2"):
        return "sentinel-2", f"sentinel-2{s[-1].lower()}"
    if s.startswith("S3"):
        return "sentinel-3", f"sentinel-3{s[-1].lower()}"
    return s.lower(), s.lower()

def build_assets_list(files: list[dict], ch_name: str) -> list[tuple[str, dict]]:
    m = re.fullmatch(r"ch_(\d+)", ch_name)
    channel = int(m.group(1)) if m else None

    assets: list[tuple[str, dict]] = []
    for f in files:
        p = f.get("path", "")
        if f.get("type") == "file" and p.lower().endswith(".raw"):
            fname = Path(p).name
            assets.append((
                fname,
                {
                    "path": p,
                    "channel": channel,
                    "file:size": int(f.get("size") or 0),
                },
            ))
    return assets

def build_edrs_item_collection(client, satellites: list[str], collection_id: str) -> ItemCollection:
    items: list[Item] = []

    for sat in satellites:
        entries = client.walk(sat) or []

        # collect session directories
        session_dirs = [e["path"] for e in entries if e.get("type") == "dir" and 
                        re.fullmatch(fr"/NOMINAL/{re.escape(sat)}/DCS_\d+_\d+_dat", e.get("path",""))]

        for sess_path in session_dirs:
            session_id = Path(sess_path).name
            # enumerate channels for this session
            ch_entries = client.walk(f"{sat}/{session_id}") or []
            channel_dirs = [
                e["path"] for e in ch_entries
                if e.get("type") == "dir" and re.search(r"/ch_\d+$", e.get("path", ""))
            ]
            # walk each channel (files: DSDB .raw + DSIB .xml)
            assets_list = []
            for ch_dir in channel_dirs:
                ch_name = ch_dir.rsplit("/", 1)[-1]
                files = client.walk(f"{sat}/{session_id}/{ch_name}") or []
                assets_list.extend(build_assets_list(files, ch_name))
            
            # add one item per session (dummy for now)
            items.append(_dummy_Item(collection=collection_id, item_id=session_id, assets_list=assets_list))

    return ItemCollection(type="FeatureCollection", features=items).to_dict()


class MockPgstacEdrs(MockPgstac):
    """pgSTAC mock for EDRS (collections from YAML)."""
    def __init__(self, request: Optional[Request] = None, readwrite: Optional[Literal["r","w"]] = None):
        super().__init__(
            request=request,
            readwrite=readwrite,
            service="edrs",
            all_collections=lambda: edrs_read_conf().get("collections", []),
            select_config=edrs_select_config,
            stac_to_odata=lambda d: d,
            map_mission=lambda *_: None,
        )
        self.sortby = "id"
    async def process_search(self, request: Request) -> dict:
        raise HTTPException(status_code=404, detail="EDRS does not support /search. Use /edrs/collections/{id}/items.")

    async def get_items(self, collection_id: str, request) -> dict:
        cfg = edrs_select_config(collection_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Collection not found")
    
        center = cfg.get("station")
        satellites = [s.strip() for s in str(cfg.get("satellite", "")).split(",") if s.strip()]
        if not satellites:
            return {"type": "FeatureCollection", "features": []}
    
        params = load_station_config(EDRS_STATIONS_CONFIG, center)
        client = EDRSConnector(**params)
        client.connect()
    
        by_session = {}
        try:
            return build_edrs_item_collection(client, satellites, collection_id)
        finally:
            try:
                client.close()
            except Exception:
                pass



def auth_validation(request: Request, collection_id: str, access_type: str):
    """
    Check if the user KeyCloak roles contain the right for this specific CADIP collection and access type.

    Args:
        collection_id (str): Used to find the CADIP station ("CADIP", "INS", "MPS", "MTI", "NSG", "SGS")
                            from the RSPY_CADIP_SEARCH_CONFIG config yaml file.
        access_type (str): The type of access, such as "download" or "read".
    """

    # Find the collection which id == the input collection_id
    collection = select_config(collection_id)
    if not collection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown CADIP collection: {collection_id!r}")
    station = collection["station"]

    # Call the authentication function from the authentication module
    authentication.auth_validation("cadip", access_type, request=request, station=station)


@router.get("/", include_in_schema=False)
async def home():
    return RedirectResponse("/edrs")

@router.get("/edrs")
async def get_root_catalog(request: Request):
    logger.info("Starting %s", request.url.path)
    authentication.auth_validation("edrs", "landing_page", request=request)
    return await request.app.state.pgstac_client.landing_page(request=request)

@router.get("/edrs/collections")
async def get_allowed_edrs_collections(request: Request) -> dict:
    logger.info("Starting %s", request.url.path)
    authentication.auth_validation("edrs", "landing_page", request=request)
    return await request.app.state.pgstac_client.all_collections(request=request)

@router.get("/edrs/collections/{collection_id}")
async def get_cadip_collection(
    request: Request,
    collection_id: Annotated[str, FPath(title="EDRS collection ID.", max_length=100, description="E.G. s1_pedc")],
) -> list[dict] | dict | stac_pydantic.Collection:
    """
    """
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_collection(collection_id, request)

@router.get("/edrs/collections/{collection_id}/items")
@handle_exceptions
async def get_edrs_collection_items(
    request: Request,
    collection_id: Annotated[str, FPath(title="EDRS collection ID.", max_length=100, description="E.G. s1_pedc")],
) -> dict:
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_items(collection_id, request)
