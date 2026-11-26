# Copyright 2023-2026 Airbus, CS Group
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

"""OData product search backed by the catalog's STAC search pipeline."""

import json
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from geojson_pydantic.geometries import Geometry
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    ValidationError,
    model_validator,
)
from rs_server_catalog.data_management.user_handler import CATALOG_SEARCH
from rs_server_catalog.middleware.catalog_middleware import UserCatalog
from rs_server_catalog.stac_api import api
from rs_server_common.utils.utils import stac_to_odata

router = APIRouter(tags=["Catalog"])


class ODataQuery(BaseModel):
    """OData query options, accepting both prefixed and unprefixed names."""

    model_config = ConfigDict(extra="forbid")

    filter: str | None = Field(
        default=None,
        alias="$filter",
        min_length=1,
        description=(
            "OData filter expression. Currently supports PublicationDate gt <start> and "
            "PublicationDate lt <end>, with inclusive bounds and timezone-aware ISO 8601 dates."
        ),
        examples=["PublicationDate gt 2026-01-01T00:00:00Z and PublicationDate lt 2026-02-01T00:00:00Z"],
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_option_names(cls, data: Any) -> Any:
        """Normalize OData 4.01 aliases and reject conflicting values."""
        if not isinstance(data, dict):
            return data
        values = data.copy()
        for name, field in cls.model_fields.items():
            alias = field.alias
            if alias is None or name not in values:
                continue
            if alias in values and values[alias] != values[name]:
                raise ValueError(f"Conflicting values for {alias} and {name}.")
            values[alias] = values.pop(name)
        return values


class PublicationDateRange(BaseModel):
    """Timezone-aware publication-date bounds extracted from an OData filter."""

    start: AwareDatetime
    end: AwareDatetime


class ODataContentDate(BaseModel):
    """Sensing dates in the current product representation."""

    Start: AwareDatetime | None
    End: AwareDatetime | None


class ODataChecksum(BaseModel):
    """Checksum metadata in the current product representation."""

    Algorithm: Literal["MD5"]
    Value: str | None
    ChecksumDate: AwareDatetime | None


class ODataProduct(BaseModel):
    """An asset exposed as a product by the current STAC-to-OData mapping."""

    Id: str
    Name: str
    ContentType: str | None
    ContentLength: int | None = Field(ge=0)
    OriginDate: AwareDatetime | None
    PublicationDate: AwareDatetime | None
    EvictionDate: AwareDatetime | None
    ContentDate: ODataContentDate
    Checksum: ODataChecksum
    ProductionType: str
    GeoFootPrint: Geometry | None


class ODataProductList(RootModel[list[ODataProduct]]):
    """The existing JSON product list, without changing its wire format."""


class ODataError(BaseModel):
    """Error representation produced by the catalog exception middleware."""

    code: str
    description: str


def publication_filter(odata_filter: str) -> str:
    """Translate the legacy, inclusive publication-date range into CQL2."""
    match = re.fullmatch(
        r"\s*PublicationDate\s+(?:gt|ge)\s+(\S+)\s+and\s+PublicationDate\s+(?:lt|le)\s+(\S+)\s*",
        odata_filter,
    )
    if not match:
        raise HTTPException(
            status_code=400,
            detail="Expected filter: PublicationDate gt <start> and PublicationDate lt <end>.",
        )
    try:
        dates = PublicationDateRange.model_validate({"start": match[1], "end": match[2]})
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail="PublicationDate bounds must be ISO 8601 datetimes with timezones.",
        ) from exc

    return f"published >= '{dates.start.isoformat()}' AND published <= '{dates.end.isoformat()}'"


@router.get(
    "/odata/v1/Products",
    summary="Search OData products",
    response_model=ODataProductList,
    responses={
        400: {"model": ODataError, "description": "Unsupported filter or query option"},
        401: {"model": ODataError, "description": "Authentication or authorization failed"},
        422: {"model": ODataError, "description": "Invalid query parameter"},
        500: {"model": ODataError, "description": "Internal server error"},
        "default": {"model": ODataError, "description": "Catalog error"},
    },
)
async def search_products(
    request: Request,
    options: Annotated[ODataQuery, Query()],
) -> ODataProductList | Response:
    """Search by publication-date range and return the matching assets as OData products."""
    if options.filter is None:
        raise HTTPException(status_code=400, detail="The $filter (or filter) query parameter is required.")
    stac_params = {"filter-lang": "cql2-text", "filter": publication_filter(options.filter)}

    # Use an independent STAC request context, retaining the authenticated state
    # without changing the public request or making another HTTP request.
    scope = {
        **request.scope,
        "path": CATALOG_SEARCH,
        "raw_path": CATALOG_SEARCH.encode(),
        "query_string": urlencode(stac_params).encode(),
    }
    search_request = Request(scope, request.receive)

    async def search(prepared_request: Request) -> Response:
        results = await api.client.get_search(
            request=prepared_request,
            filter_expr=prepared_request.query_params.get("filter"),
            filter_lang=prepared_request.query_params.get("filter-lang"),
        )
        return StreamingResponse(iter([json.dumps(results)]), media_type="application/geo+json")

    response = await UserCatalog(api.client).dispatch(search_request, search)
    if response.status_code != 200:
        return response
    return ODataProductList.model_validate(stac_to_odata(json.loads(response.body)))
