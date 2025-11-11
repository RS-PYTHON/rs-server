import copy
from typing import Optional, Literal, Annotated
from fastapi import APIRouter, Request, HTTPException, status
from fastapi import Path as FPath
from fastapi.responses import RedirectResponse
import stac_pydantic
from stac_pydantic import Item, ItemCollection
from stac_pydantic.shared import Asset
from stac_pydantic.links import Link, Links

from pathlib import Path

from xml.etree import ElementTree as ET

import re

from rs_server_common.authentication import authentication
from rs_server_common.stac_api_common import MockPgstac, handle_exceptions
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import map_stac_platform, odata_to_stac

from rs_server_edrs.edrs_utils import edrs_read_conf, edrs_select_config, edrs_session_odata_to_stac_template, edrs_sessions_stac_mapper, edrs_stac_mapper, select_config
from rs_server_edrs.edrs_client import EDRSConnector, load_station_config, EDRS_STATIONS_CONFIG

logger = Logging.default(__name__)
router = APIRouter()


def _platform_constellation_from_code(code: str) -> tuple[str | None, str | None]:
    # code ex.: "S1A", "S1C", "S2B" => returns satellites and constellation
    cfg = map_stac_platform()
    for sat in cfg["satellites"]:
        for plat, info in sat.items():
            if info.get("code") == code:
                return plat, info.get("constellation")
    return None, None

def _iso(s: str | None) -> str | None:
    if not s: return None
    # normalize "2024-04-10T08:37:00Z" -> ISO with 'Z'
    return s.replace("+00:00","Z")

def _parse_dsib_dict(dsib: dict) -> tuple[str|None,str|None,str|None,str|None,str|None]:
    hdr = dsib.get("DSIB",{}).get("Header",{})
    acq = dsib.get("DSIB",{}).get("Acquisition_Info",{})
    sat = hdr.get("Satellite")
    created = hdr.get("Generation_Time")
    start = acq.get("Start_Time")
    stop = acq.get("End_Time")
    finished = hdr.get("Generation_Time")
    return sat, _iso(start), _iso(stop), _iso(created), _iso(finished)

def _collect_session_stats(client, sat: str, session_id: str) -> tuple[dict, list[dict]]:
    """Returns (session_odata, assets_products)."""
    ch_entries = client.walk(f"{sat}/{session_id}") or []
    channel_dirs = [e["path"] for e in ch_entries if e.get("type") == "dir" and re.search(r"/ch_\d+$", e.get("path", ""))]


    starts, stops, gens = [], [], []
    assets_products: list[dict] = []
    platform_name, constellation = _platform_constellation_from_code(sat)

    for ch_dir in channel_dirs:
        ch_name = ch_dir.rsplit("/",1)[-1]   # ch_1
        ch_num = int(ch_name.split("_")[1]) if "_" in ch_name else None

        files = client.walk(f"{sat}/{session_id}/{ch_name}") or []
        # DSIB
        dsib_entry = next((f for f in files if f.get("type")=="file" and f.get("path","").lower().endswith("_dsib.xml")), None)
        dsib_dict = None
        if dsib_entry:
            dsib_dict = client.read_file(dsib_entry["path"])
        # time din DSIB
        if dsib_dict:
            sat_code, start, stop, created, finished = _parse_dsib_dict(dsib_dict)
            if start: starts.append(start)
            if stop:  stops.append(stop)
            if created: gens.append(created)

        # assets din walk (.raw)
        for f in files:
            p = f.get("path","")
            if f.get("type")=="file" and p.lower().endswith(".raw"):
                assets_products.append({
                    "SessionId": session_id.removesuffix("_dat"),
                    "File_Name": Path(p).name,
                    "Size_Bytes": int(f.get("size") or 0),
                    "href": p,                 # absolut ftp
                    "Channel": ch_num,
                    "Created": gens[-1] if gens else None,
                    "Updated": gens[-1] if gens else None
                })

    session_odata = {
        "SessionId": session_id.removesuffix("_dat"),
        "MinStart": min(starts) if starts else None,
        "MaxStop": max(stops) if stops else None,
        "MinCreated": min(gens) if gens else None,
        "MaxFinished": max(gens) if gens else None,  # fallback to Generation_Time
        "Platform": platform_name,
        "Constellation": constellation
    }
    return session_odata, assets_products

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

def _apply_asset_mapping_to_item(item: Item, asset_items: list[dict]) -> None:
    mapper = edrs_stac_mapper()
    key_field = mapper["id"]
    out_specs = {k: v for k, v in mapper.items() if k != "id"}

    for a in asset_items:
        key = a.get(key_field)
        if not key:
            continue
        out = {ok: (a.get(spec) if isinstance(spec, str) else spec)
               for ok, spec in out_specs.items()
               if not (isinstance(spec, str) and a.get(spec) is None)}
        item.assets[key] = out


def build_edrs_item_collection(client, satellites: list[str], collection_id: str, request: Request) -> ItemCollection:
    items: list[Item] = []

    service_base = str(request.url).split("/collections/")[0].rstrip("/")
    collection_href = f"{service_base}/collections/{collection_id}"
    root_href = f"{service_base}/"

    for sat in satellites:
        entries = client.walk(sat) or []

        # collect session directories
        session_dirs = [e["path"] for e in entries if e.get("type") == "dir" and 
                        re.fullmatch(fr"/NOMINAL/{re.escape(sat)}/DCS_\d+_\d+_dat", e.get("path",""))]

        for sess_path in session_dirs:
            session_id = Path(sess_path).name
            
            session, asset_products = _collect_session_stats(client, sat, session_id)

            feature = odata_to_stac(
                copy.deepcopy(edrs_session_odata_to_stac_template()),
                session,
                edrs_sessions_stac_mapper()
            )

            feature["collection"] = collection_id
            item = Item(**feature)

            _apply_asset_mapping_to_item(item, asset_products)
            self_href = f"{collection_href}/items/{item.id}"
            item.links = Links(root=[
                Link(rel="collection", type="application/json",     href=collection_href),
                Link(rel="parent",     type="application/json",     href=collection_href),
                Link(rel="root",       type="application/json",     href=root_href),
                Link(rel="self",       type="application/geo+json", href=f"{collection_href}/items/{item.id}"),
            ])
            items.append(item)

    ic_links = Links(root=[
        Link(rel="collection", type="application/json",     href=collection_href),
        Link(rel="parent",     type="application/json",     href=collection_href),
        Link(rel="root",       type="application/json",     href=root_href),
        Link(rel="self",       type="application/geo+json", href=str(request.url)),
    ])

    return ItemCollection(type="FeatureCollection", features=items, links=ic_links).to_dict()


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
            return build_edrs_item_collection(client, satellites, collection_id, request)
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


# -------------------------------
# Item by ID (pentru rel:self)
# -------------------------------
@router.get("/edrs/collections/{collection_id}/items/{session_id}")
@handle_exceptions
async def get_edrs_item(
    request: Request,
    collection_id: Annotated[str, FPath(title="EDRS collection ID.", max_length=100, description="E.G. s1_pedc")],
    session_id:    Annotated[str, FPath(title="EDRS session ID.",    max_length=200, description="E.G. DCS_01_202501270945000000112233_dat")],
) -> dict:
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")

    cfg = edrs_select_config(collection_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Collection not found")

    center = cfg.get("station")
    satellites = [s.strip() for s in str(cfg.get("satellite", "")).split(",") if s.strip()]
    if not satellites:
        raise HTTPException(status_code=404, detail="No satellites configured for this collection")

    params = load_station_config(EDRS_STATIONS_CONFIG, center)
    client = EDRSConnector(**params)
    client.connect()
    try:
        for sat in satellites:
            entries = client.walk(f"{sat}/{session_id}") or []
            if not entries:
                continue

            session, asset_products = _collect_session_stats(client, sat, session_id)

            feature = odata_to_stac(
                copy.deepcopy(edrs_session_odata_to_stac_template()),
                session,
                edrs_sessions_stac_mapper()
            )
            feature["collection"] = collection_id
            item = Item(**feature)
            _apply_asset_mapping_to_item(item, asset_products)

            # Link-urile STAC (collection/parent/root/self)
            service_base = str(request.url).split("/collections/")[0].rstrip("/")
            collection_href = f"{service_base}/collections/{collection_id}"
            root_href = f"{service_base}/"
            self_href = f"{collection_href}/items/{item.id}"
            item.links = Links(root=[
                Link(rel="collection", type="application/json",     href=collection_href),
                Link(rel="parent",     type="application/json",     href=collection_href),
                Link(rel="root",       type="application/json",     href=root_href),
                Link(rel="self",       type="application/geo+json", href=self_href),
            ])
            return item.to_dict()

        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found in collection {collection_id!r}")
    finally:
        try:
            client.close()
        except Exception:
            pass