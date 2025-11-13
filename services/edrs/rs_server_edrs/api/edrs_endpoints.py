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

import copy
import re
from pathlib import Path
from typing import Annotated, Literal

import stac_pydantic
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Request, status
from fastapi.responses import RedirectResponse
from rs_server_common.authentication import authentication
from rs_server_common.stac_api_common import (
    BBoxType,
    CollectionType,
    DateTimeType,
    FilterLangType,
    FilterType,
    LimitType,
    MockPgstac,
    PageType,
    SortByType,
    handle_exceptions,
    sort_feature_collection,
)
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import map_stac_platform, odata_to_stac
from rs_server_edrs.edrs_client import (
    EDRS_STATIONS_CONFIG,
    EDRSConnector,
    load_station_config,
)
from rs_server_edrs.edrs_utils import (
    edrs_read_conf,
    edrs_select_config,
    edrs_session_odata_to_stac_template,
    edrs_sessions_stac_mapper,
    edrs_stac_mapper,
    select_config,
)
from stac_fastapi.api.models import GeoJSONResponse
from stac_pydantic import Item, ItemCollection
from stac_pydantic.links import Link, Links
from stac_pydantic.shared import Asset

logger = Logging.default(__name__)
router = APIRouter()


def platform_constellation_from_code(code: str) -> tuple[str | None, str | None]:
    # code ex.: "S1A", "S1C", "S2B" => returns satellites and constellation
    cfg = map_stac_platform()
    for sat in cfg["satellites"]:
        for plat, info in sat.items():
            if info.get("code") == code:
                return plat, info.get("constellation")
    return None, None


def iso(s: str | None) -> str | None:
    if not s:
        return None
    # normalize "2024-04-10T08:37:00Z" -> ISO with 'Z'
    return s.replace("+00:00", "Z")


def parse_dsib_dict(dsib: dict) -> tuple[str | None, str | None, str | None, str | None, str | None]:
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
        item.assets[key] = out


def build_edrs_item_collection(client, satellites: list[str], collection_id: str, request: Request) -> ItemCollection:
    items: list[Item] = []

    service_base = str(request.url).split("/collections/")[0].rstrip("/")
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
                    Link(rel="self", type="application/geo+json", href=f"{collection_href}/items/{item.id}"),
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

    return ItemCollection(type="FeatureCollection", features=items, links=ic_links).to_dict()


class MockPgstacEdrs(MockPgstac):
    """pgSTAC mock for EDRS (collections from YAML)."""

    def __init__(self, request: Request | None = None, readwrite: Literal["r", "w"] | None = None):
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
    """ """
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_collection(collection_id, request)


@router.get(path="/edrs/collections/{collection_id}/items", response_class=GeoJSONResponse)
@handle_exceptions
async def get_edrs_collection_items(
    request: Request,
    collection_id: CollectionType,
    bbox: BBoxType = None,
    datetime: DateTimeType = None,
    filter_: FilterType = None,
    filter_lang: FilterLangType = "cql2-text",
    sortby: SortByType = None,
    limit: LimitType = None,
    page: PageType = None,
) -> dict:
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")

    item_collection: dict = await request.app.state.pgstac_client.get_items(collection_id, request)

    import json
    import re
    from datetime import datetime as DateTime
    from types import SimpleNamespace

    from fastapi import HTTPException
    from rs_server_common.rspy_models import ItemCollection
    from rs_server_common.stac_api_common import (
        MockPgstac,
        check_input_type,
        get_edrs_queryables,
    )
    from rs_server_common.utils.cql2_filter_extension import process_filter_extensions

    # Read raw query parameters and resolve effective values (query string overrides function args)
    queryParams = request.query_params
    sortByExpr = queryParams.get("sortby", sortby) or "-datetime"
    limitValue = int(queryParams.get("limit", limit) or 1000)
    pageValue = int(queryParams.get("page", page) or 1)
    filterExpr = queryParams.get("filter", filter_)
    filterLang = (queryParams.get("filter-lang", filter_lang) or "cql2-text").lower()
    dateTimeExpr = queryParams.get("datetime", datetime)

    # Normalize features to plain dicts so ItemCollection.model_validate can consume them
    featuresList = []
    for f in item_collection.get("features", []) or []:
        if isinstance(f, dict):
            featuresList.append(f)
        elif hasattr(f, "model_dump"):
            featuresList.append(f.model_dump())
        elif hasattr(f, "to_dict"):
            featuresList.append(f.to_dict())
        else:
            raise HTTPException(status_code=422, detail="Invalid feature type in collection")

    # ---------- Filtering (properties + datetime). BBOX intentionally ignored (no geometries). ----------
    queryablesRaw = get_edrs_queryables()
    allowedProps = set(queryablesRaw.keys()) | {"id"}

    # Adapt queryables for check_input_type when values are plain dicts
    fieldInfo = {}
    for k, v in queryablesRaw.items():
        if hasattr(v, "type"):
            fieldInfo[k] = v
        elif isinstance(v, dict) and "type" in v:
            fieldInfo[k] = SimpleNamespace(type=v["type"])
        else:
            fieldInfo[k] = SimpleNamespace(type="string")

    conditions = []  # list of (key, value)

    def add_condition(propName: str, value):
        key = propName
        if key.startswith("properties."):
            key = key.split(".", 1)[1]
        if key not in allowedProps:
            raise HTTPException(status_code=422, detail=f"Invalid query filter property: {propName!r}")
        # Skip type-check for id (always string), otherwise use common validator
        if key != "id":
            check_input_type(fieldInfo, key, value)
        conditions.append((key, str(value)))

    def parse_cql2_text(expr: str):
        parts = re.split(r"\bAND\b", expr, flags=re.IGNORECASE)
        for raw in parts:
            segment = raw.strip()
            if not segment:
                continue
            m = re.match(r"^([\w\:\.\-]+)\s*=\s*(.+)$", segment)
            if not m:
                raise HTTPException(status_code=422, detail=f"Invalid filter condition: {segment!r}")
            left, right = m.group(1).strip(), m.group(2).strip()
            if right.startswith(("'", '"')) and right.endswith(("'", '"')) and len(right) >= 2:
                right = right[1:-1]
            add_condition(left, right)

    def parse_cql2_json(node):
        if not isinstance(node, dict):
            raise HTTPException(status_code=422, detail="Invalid CQL2-JSON filter")
        op = str(node.get("op", "")).lower()
        args = node.get("args", [])
        if op == "and":
            for a in args:
                parse_cql2_json(a)
        elif op in {"=", "eq"} and len(args) == 2:
            left, right = args[0], args[1]
            if isinstance(left, dict) and "property" in left:
                propName = left["property"]
            elif isinstance(left, str):
                propName = left
            else:
                raise HTTPException(status_code=422, detail="Invalid CQL2-JSON left operand")
            if isinstance(right, dict) and "literal" in right:
                value = right["literal"]
            else:
                value = right
            add_condition(propName, value)
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported CQL2-JSON operator: {op}")

    if filterExpr:
        if filterLang in {"cql2-json", "application/cql+json"}:
            try:
                node = filterExpr
                if isinstance(node, str):
                    node = json.loads(node)
                node = process_filter_extensions(node)
                parse_cql2_json(node)
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Invalid CQL2-JSON filter: {e}")
        elif filterLang == "cql2-text":
            parse_cql2_text(str(filterExpr))
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported filter-lang: {filterLang}")

    # Datetime interval parsing (ISO instant or start/end)
    def parse_iso(val: str | None):
        if not val:
            return None
        s = str(val).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            return DateTime.fromisoformat(s)
        except Exception:
            try:
                return DateTime.fromisoformat(s + "T00:00:00+00:00")
            except Exception:
                return None

    def parse_interval(expr: str | None):
        if not expr:
            return None, None
        s = str(expr).strip()
        if "/" in s:
            a, b = s.split("/", 1)
            return (parse_iso(a) if a and a != ".." else None), (parse_iso(b) if b and b != ".." else None)
        t = parse_iso(s)
        return t, t

    def intersects_time(itemStart, itemEnd, qStart, qEnd):
        if qStart is None and qEnd is None:
            return True
        if itemStart is None and itemEnd is None:
            return True
        s = itemStart or itemEnd
        e = itemEnd or itemStart
        if s is None and e is None:
            return True
        if qStart and qEnd:
            return (s <= qEnd) and (e >= qStart)
        if qStart:
            return e >= qStart
        if qEnd:
            return s <= qEnd
        return True

    qStart, qEnd = parse_interval(dateTimeExpr)

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
        itemStart = parse_iso(props.get("start_datetime") or props.get("datetime"))
        itemEnd = parse_iso(props.get("end_datetime") or props.get("datetime"))
        return intersects_time(itemStart, itemEnd, qStart, qEnd)

    filteredFeatures = [f for f in featuresList if match_props(f) and match_datetime(f)]

    # Build an ItemCollection model from filtered features
    itemCollectionModel = ItemCollection.model_validate(
        {
            "type": item_collection.get("type", "FeatureCollection"),
            "features": filteredFeatures,
        },
    )

    # Create a lightweight context with the attributes expected by MockPgstac.paginate
    pagingCtx = SimpleNamespace(sortby=str(sortByExpr), limit=limitValue, page=pageValue)

    # Delegate sorting + slicing to the existing paginate implementation
    return MockPgstac.paginate(pagingCtx, itemCollectionModel)


@router.get(path="/edrs/collections/{collection_id}/items/{session_id}", response_class=GeoJSONResponse)
@handle_exceptions
async def get_edrs_item(
    request: Request,
    collection_id: CollectionType,
    session_id: str,
) -> dict:
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")

    # Reuse the existing collection builder to guarantee identical STAC mapping
    item_collection = await request.app.state.pgstac_client.get_items(collection_id, request)
    features = item_collection.get("features", [])

    # Session IDs in items are stored without the "_dat" suffix
    wanted = session_id.removesuffix("_dat")
    feature = next((f for f in features if f.get("id") == wanted), None)

    if not feature:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found in collection '{collection_id}'",
        )

    # Return the single STAC Item (Feature)
    return feature
