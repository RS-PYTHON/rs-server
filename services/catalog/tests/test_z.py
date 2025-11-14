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

"""Test that has to be executed LAST otherwise it breaks the other tests
as it deletes all the databases in the catalog."""


from starlette.status import HTTP_200_OK


def test_queryables_with_empty_catalog(client_with_empty_catalog):
    """
    Test Queryables feature endpoint when catalog has no collections in it
    """
    response_empty = client_with_empty_catalog.get("/catalog/queryables")

    assert response_empty.status_code == HTTP_200_OK
    expected_response = {
        "$id": f"{client_with_empty_catalog.base_url}/catalog/queryables",
        "type": "object",
        "title": "STAC Queryables.",
        "$schema": "https://json-schema.org/draft-07/schema#",
        "properties": {},
        "additionalProperties": True,
    }
    assert response_empty.json() == expected_response  # JSON Content Check
