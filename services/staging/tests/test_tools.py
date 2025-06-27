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
"""Module with tests for utility functions of staging processors."""

from rs_server_staging.utils.tools import get_minimal_collection_body


def test_get_minimal_collection_body():
    """Small test of get_minimal_collection_body"""
    expected = {
        "id": "abc",
        "type": "Collection",
        "description": "Collection abc automatically created by staging processor",
        "stac_version": "1.0.0",
        "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        "license": "public-domain",
        "extent": {
            "spatial": {"bbox": [[0.0, 0.0, -0.0, 0.0]]},
            "temporal": {"interval": [["2000-01-01T00:00:00Z", "2050-01-01T00:00:00Z"]]},
        },
    }

    output = get_minimal_collection_body("abc")
    assert output == expected
