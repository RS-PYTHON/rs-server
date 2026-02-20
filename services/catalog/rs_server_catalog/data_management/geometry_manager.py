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

"""Geometry validation utilities for STAC item create/update operations."""

from math import isclose
from typing import Any

from fastapi import HTTPException
from shapely.geometry import shape
from shapely.validation import explain_validity
from starlette.status import HTTP_400_BAD_REQUEST

BBOX_MATCH_TOLERANCE = 1e-9
AREA_ZERO_TOLERANCE = 1e-12


def validate_geometry_and_enforce_bbox(item: dict[str, Any]) -> dict[str, Any]:
    """
    Validate item geometry and enforce geometry/bbox consistency for Catalog item ingest/update.

    ESA/STAC requirements covered:
    - STAC-CORE-ITEM-REQ-0220 (Polygon Geometry):
      validates right-hand-rule orientation for Polygon/MultiPolygon
      (exterior ring CCW, interior rings CW).
    - STAC-CORE-ITEM-REQ-0230 (Minimum-bounding rectangle):
      enforces 2D bbox format [minLon, minLat, maxLon, maxLat] in SW->NE order.

    Behavior:
    - if `geometry` is missing/null, no geometry check is performed.
    - if `geometry` is present and `bbox` is missing, bbox is computed from geometry bounds.
    - if `geometry` and `bbox` are both present, bbox must be consistent with geometry bounds.
      In strict mode, inconsistency raises HTTP 400.
    """
    geometry = item.get("geometry")

    # Items without geometry (e.g. CADIP sessions) are accepted with no geometry checks.
    if geometry is None:
        return item

    # Validate structural/topological GeoJSON integrity first, then enforce ESA right-hand rule for polygon rings.
    shapely_geometry = validate_geometry(geometry)
    validate_polygon_geometry_orientation(geometry)

    # RFC7946/STAC bbox for 2D geometries is always [minLon, minLat, maxLon, maxLat].
    expected_bbox = [float(coord) for coord in shapely_geometry.bounds]
    item_bbox = item.get("bbox")
    if item_bbox is None:
        # Missing bbox is auto-populated from geometry bounds.
        item["bbox"] = expected_bbox
        return item

    # Parse and normalize bbox while enforcing STAC 2D shape/order constraints.
    parsed_bbox = parse_bbox(item_bbox)
    # Strict consistency mode: reject any bbox that does not match geometry bounds.
    if any(
        not isclose(parsed_bbox[index], expected_bbox[index], rel_tol=0.0, abs_tol=BBOX_MATCH_TOLERANCE)
        for index in range(4)
    ):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Inconsistent bbox for geometry. Expected {expected_bbox}, got {parsed_bbox}.",
        )

    item["bbox"] = parsed_bbox
    return item


def validate_geometry(geometry: Any):
    """
    Validate GeoJSON geometry format and Shapely validity.

    Validity checks performed:
    - geometry must be a GeoJSON object (`dict`)
    - geometry must be parseable by `shapely.shape(...)`
    - parsed geometry must not be empty
    - parsed geometry must be topologically valid (`is_valid`)

    Raises:
        HTTPException: 400 Bad Request when any validation condition fails.
    """
    if not isinstance(geometry, dict):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Invalid GeoJSON geometry: expected an object.",
        )
    try:
        # Delegate geometry parsing/validity semantics to Shapely.
        shapely_geometry = shape(geometry)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid GeoJSON geometry: {exc}",
        ) from exc

    if shapely_geometry.is_empty:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Invalid GeoJSON geometry: empty geometry is not allowed.",
        )
    # Use Shapely validity diagnostics to reject self-intersections and other topology errors.
    if not shapely_geometry.is_valid:
        reason = explain_validity(shapely_geometry)
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid GeoJSON geometry: {reason}.",
        )
    return shapely_geometry


def validate_polygon_geometry_orientation(geometry: dict[str, Any]) -> None:
    """Validate right-hand-rule orientation for Polygon and MultiPolygon."""
    geom_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    # Orientation checks apply only to Polygon-like geometries.
    if geom_type == "Polygon":
        validate_polygon_rings(coordinates, "Polygon")
    elif geom_type == "MultiPolygon":
        if not isinstance(coordinates, list):
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail="Invalid GeoJSON MultiPolygon: coordinates must be an array.",
            )
        for polygon_index, polygon in enumerate(coordinates):
            validate_polygon_rings(polygon, f"MultiPolygon[{polygon_index}]")


def validate_polygon_rings(rings: Any, geometry_label: str) -> None:
    """Validate linear rings: first exterior CCW (counterclockwise), others interior CW (clockwise)."""
    if not isinstance(rings, list) or not rings:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid {geometry_label}: expected at least one linear ring.",
        )

    # Exterior ring orientation must be CCW.
    validate_linear_ring_orientation(rings[0], expected_ccw=True, ring_label=f"{geometry_label} exterior ring")
    # Interior rings orientation must be CW.
    for ring_index, ring in enumerate(rings[1:], start=1):
        validate_linear_ring_orientation(
            ring,
            expected_ccw=False,
            ring_label=f"{geometry_label} interior ring #{ring_index}",
        )


def validate_linear_ring_orientation(ring: Any, expected_ccw: bool, ring_label: str) -> None:
    """Validate one linear ring: structure, closure, area, and orientation."""
    # A linear ring must be an ordered array of positions.
    if not isinstance(ring, list):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid {ring_label}: ring must be an array of positions.",
        )
    # GeoJSON linear rings require at least 4 positions (first point repeated at the end).
    if len(ring) < 4:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid {ring_label}: ring must contain at least 4 positions.",
        )

    # Validate ring closure: first and last positions must match.
    first_x, first_y = parse_position(ring[0], f"{ring_label} first position")
    last_x, last_y = parse_position(ring[-1], f"{ring_label} last position")
    if not (
        isclose(first_x, last_x, abs_tol=AREA_ZERO_TOLERANCE) and isclose(first_y, last_y, abs_tol=AREA_ZERO_TOLERANCE)
    ):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid {ring_label}: ring must be closed (first and last positions must match).",
        )

    # Shoelace signed area: >0 means CCW, <0 means CW.
    signed_area = 0.0
    # Iterate over each segment pair (i -> i+1) and accumulate the signed area contribution.
    for index in range(len(ring) - 1):
        x1, y1 = parse_position(ring[index], f"{ring_label} position #{index}")
        x2, y2 = parse_position(ring[index + 1], f"{ring_label} position #{index + 1}")
        signed_area += (x1 * y2) - (x2 * y1)

    # Zero signed area means degenerate geometry (aligned/repeated points), so orientation is undefined.
    if isclose(signed_area, 0.0, abs_tol=AREA_ZERO_TOLERANCE):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid {ring_label}: degenerate ring area is zero.",
        )

    # Compare actual orientation with the expected one from right-hand-rule policy.
    is_ccw = signed_area > 0.0
    if is_ccw != expected_ccw:
        expected = "counterclockwise (CCW)" if expected_ccw else "clockwise (CW)"
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid {ring_label}: expected {expected} orientation (right-hand rule).",
        )


def parse_position(position: Any, position_label: str) -> tuple[float, float]:
    """Parse [lon, lat] position and return numeric pair."""
    # GeoJSON positions are arrays like [lon, lat] (optionally with extra dimensions).
    if not isinstance(position, (list, tuple)) or len(position) < 2:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid {position_label}: expected at least [lon, lat].",
        )
    # Only longitude/latitude are used for ESA/STAC 2D orientation and bbox checks.
    longitude = parse_number(position[0], position_label)
    latitude = parse_number(position[1], position_label)
    # Return normalized numeric coordinates as float for downstream geometric computations.
    return longitude, latitude


def parse_bbox(bbox: Any) -> list[float]:
    """Parse bbox and enforce STAC length/order constraints."""
    if not isinstance(bbox, (list, tuple)):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Invalid bbox: expected an array.",
        )
    if len(bbox) != 4:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Invalid bbox: expected an array of length 4 [minLon, minLat, maxLon, maxLat].",
        )

    # Convert bbox coordinates to floats and reject non-numeric/bool values.
    parsed_bbox = [parse_number(value, "bbox") for value in bbox]
    # South-West then North-East ordering as required by STAC-CORE-ITEM-REQ-0230 – Minimum-bounding rectangle.
    if parsed_bbox[0] > parsed_bbox[2] or parsed_bbox[1] > parsed_bbox[3]:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Invalid bbox: expected southwesterly point followed by northeasterly point.",
        )
    return parsed_bbox


def parse_number(value: Any, value_label: str) -> float:
    """Parse numeric value and reject bool/non-numeric inputs."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid numeric value in {value_label}.",
        )
    return float(value)
