# Copyright 2024 CS Group
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
from rs_server_common.utils.utils import check_and_fix_timerange, validate_inputs_format


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
