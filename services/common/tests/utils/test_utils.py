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


from rs_server_common.utils.utils import check_and_fix_timerange


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
