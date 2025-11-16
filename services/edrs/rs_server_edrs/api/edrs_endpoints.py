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

"""FastAPI endpoints and helpers for the EDRS service."""

import copy
import json
import re
from datetime import datetime as DateTime
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, Literal

import stac_pydantic
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Request, status
from fastapi.responses import RedirectResponse
from rs_server_common.authentication import authentication
from rs_server_common.rspy_models import ItemCollection as RspyItemCollection

# from rs_server_common.stac_api_common import sort_feature_collection
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
    check_input_type,
    get_edrs_queryables,
    handle_exceptions,
)
from rs_server_common.utils.cql2_filter_extension import process_filter_extensions
from rs_server_common.utils.logging import Logging

from rs_server_edrs.edrs_client import (
    EDRS_STATIONS_CONFIG,
    EDRSConnector,
    load_station_config,
)
from rs_server_edrs.edrs_utils import (
    edrs_read_conf,
    edrs_select_config,
    select_config,
    build_edrs_item_collection,
)
from stac_fastapi.api.models import GeoJSONResponse
from stac_pydantic import Item
from stac_pydantic import ItemCollection as StacItemCollection
from stac_pydantic.links import Link, Links
from stac_pydantic.shared import Asset

logger = Logging.default(__name__)
router = APIRouter()



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

    # pylint: disable-next=arguments-differ  # Base class expects more args; EDRS variant only uses request.
    def process_search(
        self,
        request: Request,
    ) -> dict:
        """Signal that the EDRS API has no /search endpoint."""
        raise HTTPException(status_code=404, detail="EDRS does not support /search. Use /edrs/collections/{id}/items.")

    async def get_items(self, collection_id: str, request) -> dict:
        """Return the STAC items synthesized for the requested collection."""
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

        try:
            return build_edrs_item_collection(client, satellites, collection_id, request)
        finally:
            try:
                client.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Connector shutdown errors must be swallowed to avoid masking responses, so log and continue.
                logger.debug("Failed to close EDRS connector: %s", exc)  # nosec B110


def auth_validation(request: Request, collection_id: str, access_type: str):
    """Ensure the caller has the required CADIP permission for the collection."""

    # Find the collection which id == the input collection_id
    collection = select_config(collection_id)
    if not collection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown CADIP collection: {collection_id!r}")
    station = collection["station"]

    # Call the authentication function from the authentication module
    authentication.auth_validation("cadip", access_type, request=request, station=station)


@router.get("/", include_in_schema=False)
async def home():
    """Redirect the bare root to the /edrs catalog."""
    return RedirectResponse("/edrs")


@router.get("/edrs")
async def get_root_catalog(request: Request):
    """Return the landing-page document for the EDRS API."""
    logger.info("Starting %s", request.url.path)
    authentication.auth_validation("edrs", "landing_page", request=request)
    return await request.app.state.pgstac_client.landing_page(request=request)


@router.get("/edrs/collections")
async def get_allowed_edrs_collections(request: Request) -> dict:
    """List every EDRS collection the caller is allowed to view."""
    logger.info("Starting %s", request.url.path)
    authentication.auth_validation("edrs", "landing_page", request=request)
    return await request.app.state.pgstac_client.all_collections(request=request)


@router.get("/edrs/collections/{collection_id}")
async def get_cadip_collection(
    request: Request,
    collection_id: Annotated[str, FPath(title="EDRS collection ID.", max_length=100, description="E.G. s1_pedc")],
) -> list[dict] | dict | stac_pydantic.Collection:
    """Return the metadata for a single CADIP-backed collection."""
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_collection(collection_id, request)


@router.get(path="/edrs/collections/{collection_id}/items", response_class=GeoJSONResponse)
@handle_exceptions
async def get_edrs_collection_items(
    request: Request,
    collection_id: CollectionType,
    bbox: BBoxType = None,  # pylint: disable=unused-argument  # Accepted for API parity even if unused here.
    datetime: DateTimeType = None,
    filter_: FilterType = None,
    filter_lang: FilterLangType = "cql2-text",
    sortby: SortByType = None,
    limit: LimitType = None,
    page: PageType = None,
) -> dict:
    """Filter, sort, and page STAC Items for the requested collection."""
    # pylint: disable=too-many-branches,too-many-statements
    # Input normalization, multi-format CQL parsing, and filtering/pagination happen inline here,
    # so the flow stays verbose.
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")

    item_collection: dict = await request.app.state.pgstac_client.get_items(collection_id, request)

    # Read raw query parameters and resolve effective values (query string overrides function args)
    query_params = request.query_params
    sort_by_expr = query_params.get("sortby", sortby) or "-datetime"
    limit_value = int(query_params.get("limit", limit) or 1000)
    page_value = int(query_params.get("page", page) or 1)
    filter_expr = query_params.get("filter", filter_)
    filter_lang_value = (query_params.get("filter-lang", filter_lang) or "cql2-text").lower()
    datetime_expr = query_params.get("datetime", datetime)

    # Normalize features to plain dicts so RspyItemCollection.model_validate can consume them
    features_list = []
    for f in item_collection.get("features", []) or []:
        if isinstance(f, dict):
            features_list.append(f)
        elif hasattr(f, "model_dump"):
            features_list.append(f.model_dump())
        elif hasattr(f, "to_dict"):
            features_list.append(f.to_dict())
        else:
            raise HTTPException(status_code=422, detail="Invalid feature type in collection")

    # ---------- Filtering (properties + datetime). BBOX intentionally ignored (no geometries). ----------
    queryables_raw = get_edrs_queryables()
    allowed_props = set(queryables_raw.keys()) | {"id"}

    # Adapt queryables for check_input_type when values are plain dicts
    field_info = {}
    for k, v in queryables_raw.items():
        if hasattr(v, "type"):
            field_info[k] = v
        elif isinstance(v, dict) and "type" in v:
            field_info[k] = SimpleNamespace(type=v["type"])
        else:
            field_info[k] = SimpleNamespace(type="string")

    conditions = []  # list of (key, value)

    def add_condition(prop_name: str, value):
        key = prop_name
        if key.startswith("properties."):
            key = key.split(".", 1)[1]
        if key not in allowed_props:
            raise HTTPException(status_code=422, detail=f"Invalid query filter property: {prop_name!r}")
        # Skip type-check for id (always string), otherwise use common validator
        if key != "id":
            check_input_type(field_info, key, value)
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
                prop_name = left["property"]
            elif isinstance(left, str):
                prop_name = left
            else:
                raise HTTPException(status_code=422, detail="Invalid CQL2-JSON left operand")
            if isinstance(right, dict) and "literal" in right:
                value = right["literal"]
            else:
                value = right
            add_condition(prop_name, value)
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported CQL2-JSON operator: {op}")

    if filter_expr:
        if filter_lang_value in {"cql2-json", "application/cql+json"}:
            try:
                node = filter_expr
                if isinstance(node, str):
                    node = json.loads(node)
                node = process_filter_extensions(node)
                parse_cql2_json(node)
            except HTTPException:
                raise
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Unexpected parse issues should still surface as a uniform 422 response.
                raise HTTPException(status_code=422, detail=f"Invalid CQL2-JSON filter: {e}") from e
        elif filter_lang_value == "cql2-text":
            parse_cql2_text(str(filter_expr))
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported filter-lang: {filter_lang_value}")

    # Datetime interval parsing (ISO instant or start/end)
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
                # Any parsing failure simply means the timestamp is unusable.
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

    def intersects_time(
        item_start,
        item_end,
        q_start,
        q_end,
    ):  # pylint: disable=too-many-return-statements  # Multiple exits keep temporal logic readable.
        if q_start is None and q_end is None:
            return True
        if item_start is None and item_end is None:
            return True
        s = item_start or item_end
        e = item_end or item_start
        if s is None and e is None:
            return True
        if q_start and q_end:
            return (s <= q_end) and (e >= q_start)
        if q_start:
            return e >= q_start
        if q_end:
            return s <= q_end
        return True

    q_start, q_end = parse_interval(datetime_expr)

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

    filtered_features = [f for f in features_list if match_props(f) and match_datetime(f)]

    # Build an ItemCollection model from filtered features
    item_collection_model = RspyItemCollection.model_validate(
        {
            "type": item_collection.get("type", "FeatureCollection"),
            "features": filtered_features,
        },
    )

    # Create a lightweight context with the attributes expected by MockPgstac.paginate
    paging_ctx = SimpleNamespace(sortby=str(sort_by_expr), limit=limit_value, page=page_value)

    # Delegate sorting + slicing to the existing paginate implementation
    return MockPgstac.paginate(paging_ctx, item_collection_model)


@router.get(path="/edrs/collections/{collection_id}/items/{session_id}", response_class=GeoJSONResponse)
@handle_exceptions
async def get_edrs_item(
    request: Request,
    collection_id: CollectionType,
    session_id: str,
) -> dict:
    """Return a single STAC Item identified by session_id within the collection."""
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
