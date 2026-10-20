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

"""Shared stac-fastapi-pgstac API instance.

Since stac-fastapi-pgstac 6.4.0, the library no longer exposes module-level
``app``/``api``/``settings`` globals (see ``instantiate_api`` in
https://github.com/stac-utils/stac-fastapi-pgstac/releases/tag/6.4.0). This module builds
them once so they can be shared between ``rs_server_catalog.app`` and
``rs_server_catalog.middleware.catalog_middleware`` without a circular import.
"""

from math import isfinite

from fastapi import HTTPException, Request
from geojson_pydantic import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from geojson_pydantic.types import Position2D
from stac_fastapi.pgstac.app import instantiate_api
from stac_fastapi.pgstac.config import Settings
from stac_fastapi.pgstac.core import CoreCrudClient
from stac_fastapi.pgstac.models.links import PagingLinks
from stac_fastapi.pgstac.types.search import PgstacSearch
from stac_fastapi.types.stac import ItemCollection
from starlette.status import HTTP_400_BAD_REQUEST


def bbox_to_geometry(west: float, south: float, east: float, north: float) -> Point | LineString | Polygon:
    """Represent a non-wrapping bbox, including a point or line, as GeoJSON."""
    southwest, northeast = Position2D(west, south), Position2D(east, north)
    # A zero-width or zero-height bbox must not become an invalid, zero-area polygon.
    if west == east and south == north:
        return Point(type="Point", coordinates=southwest)
    if west == east or south == north:
        return LineString(type="LineString", coordinates=[southwest, northeast])
    return Polygon(
        type="Polygon",
        coordinates=[[southwest, Position2D(east, south), northeast, Position2D(west, north), southwest]],
    )


class CatalogSearchClient(CoreCrudClient):
    """Support 3D search bboxes over 2D item geometries at elevation zero.

    Adapt only the validated model sent to pgSTAC. The original HTTP request
    remains available to upstream GET/POST handlers for pagination links.
    This implements the STAC rule for 2D geometries, not volumetric item search.
    """

    async def _search_base(self, search_request: PgstacSearch, request: Request) -> ItemCollection:
        """Handle altitude and degenerate bboxes before invoking pgSTAC."""
        bbox = search_request.bbox
        if bbox is None:
            return await super()._search_base(search_request, request)

        # The request model already validates length and latitude/elevation order.
        # NaN can pass comparison-based bounds checks, so check finiteness first.
        if not all(isfinite(value) for value in bbox):
            raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid bbox: coordinates must be finite numbers.")
        west, south = bbox[:2]
        # STAC 3D order is [west, south, min_elevation, east, north, max_elevation].
        east, north = bbox[3:5] if len(bbox) == 6 else bbox[2:]
        if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
            raise HTTPException(HTTP_400_BAD_REQUEST, "Invalid bbox: coordinates must be within WGS84 bounds.")

        if len(bbox) == 6 and not bbox[2] <= 0 <= bbox[5]:
            # An interval excluding zero cannot intersect a 2D item geometry.
            return {
                "type": "FeatureCollection",
                "features": [],
                "links": await PagingLinks(request=request).get_links(),
                "numberMatched": 0,
                "numberReturned": 0,
            }

        if west < east and south < north:
            # Keep the native pgSTAC bbox path for ordinary rectangles.
            if len(bbox) == 6:
                # Zero is inside the elevation range here. Projecting to 2D avoids
                # pgSTAC's PolyhedralSurface conversion while preserving matches for 2D items.
                search_request = search_request.model_copy(deep=True, update={"bbox": (west, south, east, north)})
            return await super()._search_base(search_request, request)

        geometry: Point | LineString | Polygon | MultiPoint | MultiLineString | MultiPolygon | GeometryCollection
        if west > east:
            # Split antimeridian-crossing boxes instead of reversing longitude bounds.
            western = bbox_to_geometry(west, south, 180, north)
            eastern = bbox_to_geometry(-180, south, east, north)
            if isinstance(western, Polygon) and isinstance(eastern, Polygon):
                geometry = MultiPolygon(type="MultiPolygon", coordinates=[western.coordinates, eastern.coordinates])
            elif isinstance(western, LineString) and isinstance(eastern, LineString):
                geometry = MultiLineString(
                    type="MultiLineString",
                    coordinates=[western.coordinates, eastern.coordinates],
                )
            elif isinstance(western, Point) and isinstance(eastern, Point):
                geometry = MultiPoint(type="MultiPoint", coordinates=[western.coordinates, eastern.coordinates])
            else:
                # A bound exactly at +/-180 can collapse one half to a line or point;
                # mixed geometry types need a GeometryCollection.
                geometry = GeometryCollection(type="GeometryCollection", geometries=[western, eastern])
        else:
            geometry = bbox_to_geometry(west, south, east, north)

        # Copy the model without reprocessing existing filters/extensions. The
        # replacement geometry is validated above by the GeoJSON models.
        # Clear bbox because STAC makes bbox and intersects mutually exclusive.
        backend_request = search_request.model_copy(deep=True, update={"bbox": None, "intersects": geometry})
        return await super()._search_base(backend_request, request)


settings = Settings()
api = instantiate_api(client=CatalogSearchClient, settings=settings)
with_transactions = settings.enable_transactions_extensions
