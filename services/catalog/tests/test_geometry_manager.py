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

"""Tests for geometry validation and bbox consistency utilities."""

import pytest
from fastapi import HTTPException
from rs_server_catalog.data_management import geometry_manager
from rs_server_catalog.data_management.geometry_manager import (
    validate_geometry_and_enforce_bbox,
)
from shapely.geometry import shape as shapely_shape
from shapely.validation import explain_validity
from starlette.status import HTTP_400_BAD_REQUEST


def valid_polygon() -> dict:
    """Return a valid CCW Polygon used by geometry tests."""
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [-1.0, -1.0],
                [1.0, -1.0],
                [1.0, 1.0],
                [-1.0, 1.0],
                [-1.0, -1.0],
            ],
        ],
    }


@pytest.mark.unit
def test_accept_item_without_geometry_and_bbox():
    """Items without geometry and bbox are accepted unchanged."""
    item = {"id": "cadip-session"}
    result = validate_geometry_and_enforce_bbox(item)
    assert result == item
    assert "bbox" not in result


@pytest.mark.unit
def test_compute_bbox_when_missing():
    """Bbox is computed from geometry when missing."""
    item = {"id": "item-1", "geometry": valid_polygon()}
    result = validate_geometry_and_enforce_bbox(item)
    assert result["bbox"] == [-1.0, -1.0, 1.0, 1.0]


@pytest.mark.unit
def test_reject_bbox_with_length_six():
    """Bbox with 6 coordinates is rejected (strict STAC len=4)."""
    item = {
        "id": "item-2",
        "geometry": valid_polygon(),
        "bbox": [-1.0, -1.0, 1.0, 1.0, 0.0, 10.0],
    }
    with pytest.raises(HTTPException) as exc_info:
        validate_geometry_and_enforce_bbox(item)
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert "length 4" in str(exc_info.value.detail)


@pytest.mark.unit
def test_reject_inconsistent_bbox():
    """Inconsistent bbox vs geometry is rejected."""
    item = {
        "id": "item-3",
        "geometry": valid_polygon(),
        "bbox": [-180.0, -90.0, 180.0, 90.0],
    }
    with pytest.raises(HTTPException) as exc_info:
        validate_geometry_and_enforce_bbox(item)
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert "Inconsistent bbox" in str(exc_info.value.detail)


@pytest.mark.unit
def test_reject_wrong_polygon_orientation():
    """Clockwise exterior ring is rejected by right-hand-rule check."""
    item = {
        "id": "item-4",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-1.0, -1.0],
                    [-1.0, 1.0],
                    [1.0, 1.0],
                    [1.0, -1.0],
                    [-1.0, -1.0],
                ],
            ],
        },
    }
    with pytest.raises(HTTPException) as exc_info:
        validate_geometry_and_enforce_bbox(item)
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert "right-hand rule" in str(exc_info.value.detail)


@pytest.mark.unit
def test_reject_geometry_not_an_object():
    """Non-object geometry is rejected."""
    item = {"id": "item-5", "geometry": "not-an-object"}
    with pytest.raises(HTTPException) as exc_info:
        validate_geometry_and_enforce_bbox(item)
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid GeoJSON geometry: expected an object."


@pytest.mark.unit
def test_reject_empty_geometry():
    """Empty geometries are rejected."""
    item = {"id": "item-6", "geometry": {"type": "GeometryCollection", "geometries": []}}
    with pytest.raises(HTTPException) as exc_info:
        validate_geometry_and_enforce_bbox(item)
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid GeoJSON geometry: empty geometry is not allowed."


@pytest.mark.unit
def test_reject_invalid_geometry_with_explain_validity_reason():
    """Invalid geometries are rejected with Shapely explain_validity reason."""
    invalid_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [0.0, 0.0],
                [1.0, 1.0],
                [1.0, 0.0],
                [0.0, 1.0],
                [0.0, 0.0],
            ],
        ],
    }
    expected_reason = explain_validity(shapely_shape(invalid_polygon))

    item = {"id": "item-7", "geometry": invalid_polygon}
    with pytest.raises(HTTPException) as exc_info:
        validate_geometry_and_enforce_bbox(item)
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == f"Invalid GeoJSON geometry: {expected_reason}."


@pytest.mark.unit
def test_reject_polygon_with_no_linear_rings(monkeypatch):
    """Polygon with empty coordinate rings is rejected by the right-hand-rule ring validator."""

    # Force validate_geometry() to succeed so we can reach the ring-structure validation.
    monkeypatch.setattr(geometry_manager, "validate_geometry", lambda _geometry: shapely_shape(valid_polygon()))

    item = {"id": "item-8", "geometry": {"type": "Polygon", "coordinates": []}}
    with pytest.raises(HTTPException) as exc_info:
        geometry_manager.validate_geometry_and_enforce_bbox(item)
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid Polygon: expected at least one linear ring."
