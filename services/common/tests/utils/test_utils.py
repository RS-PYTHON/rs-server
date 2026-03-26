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

"""Unit tests for utility funtions defined in utils.py."""

from datetime import datetime

import pytest
from rs_server_common.utils.utils import (
    _iter_external_id_parts,
    apply_external_ids,
    check_and_fix_timerange,
    find_product_type,
    normalize_external_ids,
    repair_and_orient_geojson_geometry,
    validate_inputs_format,
)


def test_add_end_datetime():
    """Test when start_datetime exists but end_datetime is missing"""
    item = {
        "properties": {
            "start_datetime": "2024-01-01T00:00:00Z",
            "end_datetime": None,
            "datetime": "2024-01-02T00:00:00Z",
        },
    }
    check_and_fix_timerange(item)
    assert item["properties"]["end_datetime"] == "2024-01-02T00:00:00Z"


def test_remove_end_datetime():
    """Test when end_datetime exists but start_datetime is missing"""
    item = {
        "properties": {
            "start_datetime": None,
            "end_datetime": "2024-01-02T00:00:00Z",
            "datetime": "2024-01-01T00:00:00Z",
        },
    }
    check_and_fix_timerange(item)
    assert item["properties"].get("end_datetime", None) is None


def test_no_change():
    """Test when both start_datetime and end_datetime are properly defined"""
    item = {
        "properties": {
            "start_datetime": "2024-01-01T00:00:00Z",
            "end_datetime": "2024-01-02T00:00:00Z",
            "datetime": None,
        },
    }
    check_and_fix_timerange(item)
    assert item["properties"]["start_datetime"] == "2024-01-01T00:00:00Z"
    assert item["properties"]["end_datetime"] == "2024-01-02T00:00:00Z"


def test_missing_datetimes():
    """Test when both start_datetime and end_datetime are missing"""
    item = {
        "properties": {
            "start_datetime": None,
            "end_datetime": None,
            "datetime": None,
        },
    }
    check_and_fix_timerange(item)
    assert item["properties"].get("end_datetime", None) is None
    assert item["properties"].get("start_datetime", None) is None


@pytest.mark.parametrize(
    "date_time, expected",
    [
        # Simple cases with timezone
        ("1996-12-19T16:39:57-00:00", ("1996-12-19T16:39:57-00:00", "", "")),
        ("1996-12-19T16:39:57+00:00", ("1996-12-19T16:39:57+00:00", "", "")),
        ("1996-12-19T16:39:57-08:00", ("1996-12-19T16:39:57-08:00", "", "")),
        ("1996-12-19T16:39:57+08:00", ("1996-12-19T16:39:57+08:00", "", "")),
        # Closed ranges
        (
            "1985-04-12T23:20:50.52+01:00/1986-04-12T23:20:50.52+01:00",
            ("", "1985-04-12T23:20:50.52+01:00", "1986-04-12T23:20:50.52+01:00"),
        ),
        (
            "1985-04-12T23:20:50.52-01:00/1986-04-12T23:20:50.52-01:00",
            ("", "1985-04-12T23:20:50.52-01:00", "1986-04-12T23:20:50.52-01:00"),
        ),
        # Open ranges
        ("../2024-01-02T23:59:59Z", ("", "..", "2024-01-02T23:59:59Z")),
        ("2024-01-01T00:00:00Z/..", ("", "2024-01-01T00:00:00Z", "..")),
        # Fractions
        ("1937-01-01T12:00:27.87+01:00", ("1937-01-01T12:00:27.87+01:00", "", "")),
        ("1937-01-01T12:00:27.8710+01:00", ("1937-01-01T12:00:27.8710+01:00", "", "")),
        ("1937-01-01T12:00:27.8+01:00", ("1937-01-01T12:00:27.8+01:00", "", "")),
        ("2020-07-23T00:00:00.000+03:00", ("2020-07-23T00:00:00.000+03:00", "", "")),
        ("2020-07-23T00:00:00+03:00", ("2020-07-23T00:00:00+03:00", "", "")),
        # With Z
        ("2020-07-23T00:00:00.0123456Z", ("2020-07-23T00:00:00.0123456Z", "", "")),
        ("2020-07-23T00:00:00.01234567Z", ("2020-07-23T00:00:00.01234567Z", "", "")),
        ("2020-07-23T00:00:00.012345678Z", ("2020-07-23T00:00:00.012345678Z", "", "")),
        # Empty
        ("", (None, None, None)),
    ],
)
def test_validate_inputs_format(date_time: str, expected: tuple[str, str, str]):
    """Test datetime formats"""
    fixed_str, start_str, stop_str = expected
    fixed_dt, start_dt, stop_dt = validate_inputs_format(date_time, raise_errors=False)

    def check_dt(dt: datetime, s: str):
        assert dt is not None, f"parsed datetime is None instead of {s}"
        assert dt.isoformat() == datetime.fromisoformat(s.replace("Z", "+00:00")).isoformat()

    if fixed_str:
        check_dt(fixed_dt, fixed_str)
    else:
        assert fixed_dt is None

    if start_str and start_str != "..":
        check_dt(start_dt, start_str)
    else:
        assert start_dt is None

    if stop_str and stop_str != "..":
        check_dt(stop_dt, stop_str)
    else:
        assert stop_dt is None


product_type_data = {
    "productType": "S01SIWRAW",
    "mission": "S1",
    "instrumentMode": "IW",
    "processingLevel": "RAW",
    "legacyType": "IW_RAW__0N",
}

# All 36 legacyType values
all_legacy_types = [
    "S1_GRDF_1S",
    "S2_GRDF_1S",
    "S3_GRDF_1S",
    "S4_GRDF_1S",
    "S5_GRDF_1S",
    "S6_GRDF_1S",
    "S1_GRDF_1A",
    "S2_GRDF_1A",
    "S3_GRDF_1A",
    "S4_GRDF_1A",
    "S5_GRDF_1A",
    "S6_GRDF_1A",
    "S1_GRDH_1S",
    "S2_GRDH_1S",
    "S3_GRDH_1S",
    "S4_GRDH_1S",
    "S5_GRDH_1S",
    "S6_GRDH_1S",
    "S1_GRDH_1A",
    "S2_GRDH_1A",
    "S3_GRDH_1A",
    "S4_GRDH_1A",
    "S5_GRDH_1A",
    "S6_GRDH_1A",
    "S1_GRDM_1S",
    "S2_GRDM_1S",
    "S3_GRDM_1S",
    "S4_GRDM_1S",
    "S5_GRDM_1S",
    "S6_GRDM_1S",
    "S1_GRDM_1A",
    "S2_GRDM_1A",
    "S3_GRDM_1A",
    "S4_GRDM_1A",
    "S5_GRDM_1A",
    "S6_GRDM_1A",
]


def test_all_legacy_types_match():
    """Test that all 36 legacy types are matched by the single regex."""
    for legacy in all_legacy_types:
        legacy_type_entry = find_product_type(legacy)
        assert legacy_type_entry, f"No match found for {legacy}"
        assert legacy_type_entry["legacyType"] == "S[1-6]_GRD[FHM]_1[AS]"
        assert legacy_type_entry["productType"] == "S01SSMGRD"
        assert legacy_type_entry["mission"] == "S1"
        assert legacy_type_entry["instrumentMode"] == "SM"
        assert legacy_type_entry["processingLevel"] == "GRD"


def test_regex_error_fallback_branch(monkeypatch):
    """Covers: invalid regex raises re.error → equality fallback → returns item"""
    broken_entry = {
        "productType": "BROKEN",
        "mission": "S0",
        "instrumentMode": "XX",
        "processingLevel": "TEST",
        "legacyType": "[invalid_regex",
    }

    # Monkeypatch product_type_data with a list containing both
    if isinstance(product_type_data, list):
        temp_data = product_type_data + [broken_entry]
    else:
        temp_data = [product_type_data, broken_entry]

    monkeypatch.setattr("rs_server_common.utils.utils.product_type_data", temp_data)

    result = find_product_type("[invalid_regex")
    assert result == broken_entry, "Expected equality fallback match"


def test_regex_types_match_auxip():
    """Test legacy type are matched by the single regex."""
    legacy_type_entry = find_product_type("SR_2_CP00AX")
    assert legacy_type_entry["productType"] == "S00__ADF_MSLPC"

    # invalid regex for S00__ADF_MSLPC
    legacy_type_entry = find_product_type("SR_2_CP224AX")
    assert legacy_type_entry["productType"] is None


def test_iter_external_id_parts_splits_and_strips():
    """Iterates externalIds input and removes empty parts."""
    values = list(_iter_external_id_parts("cadip:123, auxip:456,,  "))
    assert values == ["cadip:123", "auxip:456"]


def test_iter_external_id_parts_list_input():
    """Iterates list values and handles comma-separated parts."""
    values = list(_iter_external_id_parts(["cadip:123", " auxip:456,prip:789", None]))
    assert values == ["cadip:123", "auxip:456", "prip:789"]


def test_normalize_external_ids_for_scheme():
    """Normalizes mixed externalIds and keeps values for the target scheme."""
    normalized = normalize_external_ids("123, auxip:456, cadip:789", "auxip")
    assert normalized == ["123", "456"]


def test_normalize_external_ids_scheme_only():
    """Scheme-only input returns None to indicate match-all for scheme."""
    normalized = normalize_external_ids("auxip:", "auxip")
    assert normalized is None


def test_normalize_external_ids_other_scheme_only():
    """Other-scheme-only input returns empty list for no match."""
    normalized = normalize_external_ids("cadip:", "auxip")
    assert normalized == []


def test_apply_external_ids_no_external_ids():
    """Leaves params unchanged when externalIds is absent."""
    params = {"platform": "S1"}
    assert apply_external_ids(params, "auxip") == {"platform": "S1"}


def test_apply_external_ids_scheme_only():
    """Drops externalIds when scheme-only is provided (match all)."""
    params = {"externalIds": "auxip:"}
    assert not apply_external_ids(params, "auxip")


def test_apply_external_ids_no_match():
    """Sets __no_match__ when externalIds has only other-scheme values."""
    params = {"externalIds": "cadip:"}
    assert apply_external_ids(params, "auxip") == {"externalIds": "__no_match__"}


def test_apply_external_ids_single_value():
    """Maps a single normalized value to externalIds."""
    params = {"externalIds": "auxip:456"}
    assert apply_external_ids(params, "auxip") == {"externalIds": "456"}


def test_apply_external_ids_multiple_values():
    """Maps multiple normalized values to externalIdss list."""
    params = {"externalIds": "123, auxip:456"}
    assert apply_external_ids(params, "auxip") == {"externalIdss": ["123", "456"]}


@pytest.mark.parametrize(
    "geometry",
    [
        {"type": "Point", "coordinates": [1.0, 2.0]},
        {"type": "LineString", "coordinates": [[1.0, 2.0], [3.0, 4.0]]},
    ],
)
def test_repair_and_orient_geojson_geometry_keeps_non_polygon_geometry_unchanged(geometry):
    """Leaves non-polygon geometries unchanged."""
    assert repair_and_orient_geojson_geometry(geometry) == geometry


def test_repair_and_orient_geojson_geometry_keeps_geometry_collection_with_polygon_and_line():
    """Repairs an invalid polygon and keeps the full mixed GeometryCollection returned by make_valid."""
    geometry = {
        "type": "Polygon",
        "coordinates": [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (1.0, 1.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0)]],
    }

    assert repair_and_orient_geojson_geometry(geometry) == {
        "type": "GeometryCollection",
        "geometries": [
            {
                "type": "Polygon",
                "coordinates": (((2.0, 0.0), (0.0, 0.0), (0.0, 2.0), (2.0, 2.0), (2.0, 0.0)),),
            },
            {"type": "LineString", "coordinates": ((2.0, 2.0), (1.0, 1.0))},
        ],
    }


def test_repair_and_orient_geojson_geometry_keeps_geometry_collection_with_multipolygon_and_line():
    """Repairs an invalid polygon and keeps the full mixed GeometryCollection returned by make_valid."""
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                (0.0, 0.0),
                (4.0, 0.0),
                (4.0, 4.0),
                (0.0, 4.0),
                (0.0, 0.0),
                (2.0, 2.0),
                (5.0, 2.0),
                (5.0, 5.0),
                (2.0, 5.0),
                (2.0, 2.0),
                (0.0, 0.0),
            ],
        ],
    }

    assert repair_and_orient_geojson_geometry(geometry) == {
        "type": "GeometryCollection",
        "geometries": [
            {
                "type": "MultiPolygon",
                "coordinates": [
                    (((2.0, 4.0), (2.0, 2.0), (4.0, 2.0), (4.0, 0.0), (0.0, 0.0), (0.0, 4.0), (2.0, 4.0)),),
                    (((2.0, 5.0), (5.0, 5.0), (5.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0), (2.0, 5.0)),),
                ],
            },
            {"type": "LineString", "coordinates": ((0.0, 0.0), (2.0, 2.0))},
        ],
    }


def test_repair_and_orient_geojson_geometry_returns_non_polygonal_make_valid_output():
    """Returns non-polygonal make_valid output unchanged."""
    geometry = {
        "type": "Polygon",
        "coordinates": [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (1.0, 0.0), (0.0, 0.0), (0.0, 0.0)]],
    }

    assert repair_and_orient_geojson_geometry(geometry) == {
        "type": "MultiLineString",
        "coordinates": (((0.0, 0.0), (1.0, 0.0)), ((1.0, 0.0), (2.0, 0.0))),
    }
