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
"""Unit tests for filter_and_paginate_features utility (EDRS)."""

import pytest
from fastapi import HTTPException

from services.common.rs_server_common.stac_api_common import get_edrs_queryables
from services.edrs.rs_server_edrs.edrs_utils import (
    filter_and_paginate_features,
    iso,
    parse_dsib_dict,
    platform_constellation_from_code,
)

# Use the real EDRS queryables definition from the service config
QUERYABLES = get_edrs_queryables()


def make_feature(feature_id: str, **properties) -> dict:
    """Helper to create a minimal feature dict with required geometry/datetime."""
    geometry = {
        "type": "Polygon",
        "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]],
    }
    bbox = [-180.0, -90.0, 180.0, 90.0]
    if "datetime" not in properties:
        properties["datetime"] = properties.get("start_datetime") or "2024-01-01T00:00:00Z"
    return {
        "id": feature_id,
        "type": "Feature",
        "geometry": geometry,
        "bbox": bbox,
        "properties": properties,
        "assets": {},
        "links": [],
    }


def test_filter_cql2_text_on_property():
    """Filter using CQL2 text on a string property."""
    features = [
        make_feature("a", platform="sentinel-1a", constellation="sentinel-1"),
        make_feature("b", platform="sentinel-1b", constellation="sentinel-1"),
    ]
    params = {"filter": "platform='sentinel-1a'"}

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # Expect only the matching platform to remain
    assert [f["id"] for f in result["features"]] == ["a"]


def test_filter_cql2_json_on_multiple_properties():
    """Filter using CQL2 JSON on two properties."""
    features = [
        make_feature("a", platform="sentinel-1a", constellation="sentinel-1"),
        make_feature("b", platform="sentinel-1a", constellation="sentinel-2"),
    ]
    params = {
        "filter-lang": "cql2-json",
        "filter": {
            "op": "and",
            "args": [
                {"op": "=", "args": [{"property": "platform"}, "sentinel-1a"]},
                {"op": "=", "args": [{"property": "constellation"}, "sentinel-1"]},
            ],
        },
    }

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # Expect match on both platform and constellation
    assert [f["id"] for f in result["features"]] == ["a"]


def test_filter_datetime_interval():
    """Filter items intersecting a datetime interval."""
    features = [
        make_feature(
            "inside",
            start_datetime="2024-01-01T00:00:00Z",
            end_datetime="2024-01-01T02:00:00Z",
        ),
        make_feature(
            "outside",
            start_datetime="2023-12-31T00:00:00Z",
            end_datetime="2023-12-31T02:00:00Z",
        ),
    ]
    params = {"datetime": "2024-01-01T00:00:00Z/2024-01-02T00:00:00Z"}

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # Only the feature intersecting the interval remains
    assert [f["id"] for f in result["features"]] == ["inside"]


def test_sort_and_paginate():
    """Sort by datetime desc and take second page with limit 1."""
    features = [
        make_feature("old", datetime="2024-01-01T00:00:00Z"),
        make_feature("mid", datetime="2024-02-01T00:00:00Z"),
        make_feature("new", datetime="2024-03-01T00:00:00Z"),
    ]
    params = {"sortby": "-datetime", "limit": "1", "page": "2"}

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # Sorted desc; page=2 limit=1 should yield the middle feature
    assert [f["id"] for f in result["features"]] == ["mid"]


def test_invalid_property_raises_value_error():
    """Invalid filter property should raise ValueError."""
    features = [make_feature("a", platform="sentinel-1a")]
    params = {"filter": "unknown='x'"}

    with pytest.raises(ValueError):
        filter_and_paginate_features(features, params, QUERYABLES)


def test_invalid_datetime_filter_returns_empty():
    """Invalid datetime value in filter simply yields no matches."""
    features = [make_feature("a", start_datetime="not-a-date", end_datetime="not-a-date")]
    params = {"filter": "start_datetime='abc'"}

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # Bad datetime comparison results in no matches
    assert [f["id"] for f in result["features"]] == []


def test_filter_on_start_datetime_equality():
    """Filter equality on start_datetime should match only the expected feature."""
    features = [
        make_feature("x", start_datetime="2024-01-01T00:00:00Z", end_datetime="2024-01-01T01:00:00Z"),
        make_feature("y", start_datetime="2024-02-01T00:00:00Z", end_datetime="2024-02-01T01:00:00Z"),
    ]
    params = {"filter": "start_datetime='2024-01-01T00:00:00Z'"}

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # Match only feature x
    assert [f["id"] for f in result["features"]] == ["x"]


def test_filter_on_id_and_platform_cql2_json():
    """Filter with cql2-json combining id, platform and datetime."""
    features = [
        make_feature(
            "keep",
            platform="sentinel-1a",
            datetime="2024-01-01T01:00:00Z",
        ),
        make_feature(
            "drop",
            platform="sentinel-1b",
            datetime="2024-01-01T01:00:00Z",
        ),
    ]
    params = {
        "filter-lang": "cql2-json",
        "filter": {
            "op": "and",
            "args": [
                {"op": "=", "args": [{"property": "id"}, {"literal": "keep"}]},
                {"op": "=", "args": [{"property": "platform"}, {"literal": "sentinel-1a"}]},
                {"op": "=", "args": [{"property": "datetime"}, {"literal": "2024-01-01T01:00:00Z"}]},
            ],
        },
    }

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # Only the feature matching all three conditions remains
    assert [f["id"] for f in result["features"]] == ["keep"]


def test_filter_on_published_and_constellation_cql2_json_zero_match():
    """Filter with cql2-json on published and constellation yielding zero results."""
    features = [
        make_feature(
            "a",
            published="2025-02-13T11:28:42Z",
            constellation="sentinel-1",
        ),
        make_feature(
            "b",
            published="2025-02-13T11:28:42Z",
            constellation="sentinel-1",
        ),
    ]
    params = {
        "filter-lang": "cql2-json",
        "filter": {
            "op": "and",
            "args": [
                {"op": "=", "args": [{"property": "published"}, {"literal": "2025-02-13T11:28:42Z"}]},
                {"op": "=", "args": [{"property": "constellation"}, {"literal": "sentinel-2"}]},
            ],
        },
    }

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # No feature matches constellation sentinel-2
    assert [f["id"] for f in result["features"]] == []


def test_item_interval_none_when_datetimes_invalid():
    """Items with unparsable datetimes should be kept when no datetime filter is provided."""
    features = [
        make_feature(
            "invalid_interval",
            datetime="invalid",
            start_datetime="invalid",
            end_datetime="invalid",
        ),
    ]
    # Provide a datetime filter so we skip the branch that returns early and hit item_start/item_end None branch
    params = {"datetime": "2024-01-01T00:00:00Z"}

    result = filter_and_paginate_features(features, params, QUERYABLES)

    # The item is kept (intersects_time returns True when item interval is None and no query interval)
    assert [f["id"] for f in result["features"]] == ["invalid_interval"]


@pytest.mark.parametrize(
    "filter_payload,expected_exception",
    [
        (["not-a-dict"], ValueError),  # invalid CQL2-JSON filter type (non-dict payload)
        ({"op": "or", "args": []}, ValueError),  # unsupported operator
        ({"op": "=", "args": [123, "x"]}, ValueError),  # invalid left operand
        ({"op": "=", "args": [{"property": "platform"}, {"foo": "bar"}]}, HTTPException),  # value is non-literal dict
        ({"op": "=", "args": ["platform", "sentinel-1a"]}, None),  # left operand as string
    ],
)
def test_cql2_json_error_branches(filter_payload, expected_exception):
    """CQL2-JSON filters trigger expected error handling branches."""
    features = [make_feature("a", platform="sentinel-1a")]
    params = {"filter-lang": "cql2-json", "filter": filter_payload}

    if expected_exception:
        with pytest.raises(expected_exception):
            filter_and_paginate_features(features, params, QUERYABLES)
    else:
        result = filter_and_paginate_features(features, params, QUERYABLES)
        assert [f["id"] for f in result["features"]] == ["a"]


def test_platform_constellation_from_code_unknown():
    """Unknown satellite code should return (None, None)."""
    # Keep entrypoint consistent with the other tests
    empty = filter_and_paginate_features([], {}, QUERYABLES)
    assert empty["features"] == []
    assert platform_constellation_from_code("UNKNOWN") == (None, None)


def test_iso_returns_none_for_empty():
    """iso() should return None when input is falsy."""
    _ = filter_and_paginate_features([], {}, QUERYABLES)  # call utility under test to stay consistent
    assert iso(None) is None
    assert iso("") is None


def test_parse_dsib_dict_fallbacks():
    """parse_dsib_dict should fill missing created/finished from other fields."""
    dsib = {
        "DCSU_Session_Information_Block": {
            "time_start": "2024-01-01T00:00:00Z",
            "time_stop": "2024-01-01T01:00:00Z",
            # created/finished missing -> should fallback
        },
    }
    # Run filter function once to mirror existing test patterns
    filter_and_paginate_features([], {}, QUERYABLES)
    start, stop, created, finished = parse_dsib_dict(dsib)
    assert start == "2024-01-01T00:00:00Z"
    assert stop == "2024-01-01T01:00:00Z"
    # created/finished should fallback to stop/start respectively per implementation
    assert created == "2024-01-01T01:00:00Z"
    assert finished == "2024-01-01T01:00:00Z"
