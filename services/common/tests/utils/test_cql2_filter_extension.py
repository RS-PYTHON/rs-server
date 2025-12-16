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

"""Test file for 'cql2_filter_extension.py'"""

import pytest
from rs_server_common.utils.cql2_filter_extension import (
    Cql2FilterFormattingError,
    process_filter_extensions,
)


def test_filter_processing_with_correct_subfilters():
    """Test nominal case with correct filters and subfilters."""

    # Case 1: real test-case filter, with operations between datetimes and integers
    input_filter_1 = {
        "op": "t_contains",
        "args": [
            {"interval": [{"property": "start_datetime"}, {"property": "end_datetime"}]},
            {
                "interval": [
                    {"op": "-", "args": ["2024-05-27T09:44:12.509000Z", 1]},
                    {"op": "+", "args": ["2024-05-27T09:44:13.509000Z", 3600]},
                ],
            },
        ],
    }

    # Case 2: fictive filter with expected format and only one operation between two integers
    input_filter_2 = {
        "op": "whatever_operator",
        "args": [
            {"interval": [{"property": "first_property"}, {"property": "second_property"}]},
            {"interval": ["2024-05-27T09:44:12.509000Z", {"op": "+", "args": [1000, 444]}]},
        ],
    }

    # Case 3: filter with only an operation, outside of an interval. Here the operation should not be processed
    # and the filter remain the same
    input_filter_3 = {"op": "+", "args": ["2024-05-27T09:44:13.509000Z", 3600]}

    expected_filter_1 = {
        "op": "t_contains",
        "args": [
            {"interval": [{"property": "start_datetime"}, {"property": "end_datetime"}]},
            {"interval": ["2024-05-27T09:44:11.509000Z", "2024-05-27T10:44:13.509000Z"]},
        ],
    }

    expected_filter_2 = {
        "op": "whatever_operator",
        "args": [
            {"interval": [{"property": "first_property"}, {"property": "second_property"}]},
            {"interval": ["2024-05-27T09:44:12.509000Z", "1444"]},
        ],
    }

    assert process_filter_extensions(input_filter_1) == expected_filter_1
    assert process_filter_extensions(input_filter_2) == expected_filter_2
    assert process_filter_extensions(input_filter_3) == input_filter_3


def test_filter_processing_error_cases():
    """Test error cases"""

    # Case 1: truncated operation subfilter
    input_filter_1 = {
        "op": "whatever_operator",
        "args": [
            {"interval": [{"property": "first_property"}, {"property": "second_property"}]},
            {"interval": ["2024-05-27T09:44:12.509000Z", {"op": "+", "somefield": 1000}]},
        ],
    }
    with pytest.raises(Cql2FilterFormattingError) as error1:
        process_filter_extensions(input_filter_1)
    assert error1.value.args[0] == "Missing field 'op' or 'args' in operation filter: {'op': '+', 'somefield': 1000}"

    # Case 2: wrong number of args
    input_filter_2 = {
        "op": "whatever_operator",
        "args": [
            {"interval": [{"property": "first_property"}, {"property": "second_property"}]},
            {"interval": ["2024-05-27T09:44:12.509000Z", {"op": "+", "args": [1000]}]},
        ],
    }
    with pytest.raises(Cql2FilterFormattingError) as error2:
        process_filter_extensions(input_filter_2)
    assert error2.value.args[0] == "Expected exactly two values in field 'args': {'op': '+', 'args': [1000]}"

    # Case 3: unsupported operator
    input_filter_3 = {
        "op": "whatever_operator",
        "args": [
            {"interval": [{"property": "first_property"}, {"property": "second_property"}]},
            {"interval": ["2024-05-27T09:44:12.509000Z", {"op": ">", "args": [1000, 444]}]},
        ],
    }
    with pytest.raises(Cql2FilterFormattingError) as error3:
        process_filter_extensions(input_filter_3)
    assert error3.value.args[0] == "Unknown operator: >. Accepted operators are: ['+', '-']."

    # Case 4: invalid datetime
    input_filter_4 = {
        "op": "whatever_operator",
        "args": [
            {"interval": [{"property": "first_property"}, {"property": "second_property"}]},
            {"interval": ["2024-05-27T09:44:12.509000Z", {"op": "+", "args": ["22/10/2025:17.00.00", 444]}]},
        ],
    }
    with pytest.raises(Cql2FilterFormattingError) as error4:
        process_filter_extensions(input_filter_4)
    assert (
        error4.value.args[0]
        == "Cannot process value 22/10/2025:17.00.00: only int, float or valid datetimes are allowed."
    )
