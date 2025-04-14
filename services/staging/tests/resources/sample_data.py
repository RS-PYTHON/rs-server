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

"""Sample data for tests."""

# Sample dataProcessMetadataModel instance copy/pasted from the swagger page
# for the '/processes/{resource}/execution' endpoint.
# Replace true by True.
sample_process_metadata_model = {
    "inputs": {
        "collection": "string",
        "items": {
            "href": "string",
            "value": {
                "type": "string",
                "features": [
                    {
                        "type": "string",
                        "geometry": {},
                        "properties": {
                            "additionalProp1": "string",
                            "additionalProp2": "string",
                            "additionalProp3": "string",
                        },
                        "bbox": [0, 0],
                        "id": "string",
                        "stac_version": "string",
                        "assets": {
                            "additionalProp1": {
                                "title": "string",
                                "description": "string",
                                "start_datetime": "2025-04-01T12:57:20.505Z",
                                "end_datetime": "2025-04-01T12:57:20.505Z",
                                "created": "2025-04-01T12:57:20.505Z",
                                "updated": "2025-04-01T12:57:20.505Z",
                                "platform": "string",
                                "instruments": ["string"],
                                "constellation": "string",
                                "mission": "string",
                                "providers": [
                                    {"name": "string", "description": "string", "roles": ["string"], "url": "string"},
                                ],
                                "gsd": 1,
                                "href": "string",
                                "type": "string",
                                "roles": ["string"],
                            },
                            "additionalProp2": {
                                "title": "string",
                                "description": "string",
                                "start_datetime": "2025-04-01T12:57:20.505Z",
                                "end_datetime": "2025-04-01T12:57:20.505Z",
                                "created": "2025-04-01T12:57:20.505Z",
                                "updated": "2025-04-01T12:57:20.505Z",
                                "platform": "string",
                                "instruments": ["string"],
                                "constellation": "string",
                                "mission": "string",
                                "providers": [
                                    {"name": "string", "description": "string", "roles": ["string"], "url": "string"},
                                ],
                                "gsd": 1,
                                "href": "string",
                                "type": "string",
                                "roles": ["string"],
                            },
                            "additionalProp3": {
                                "title": "string",
                                "description": "string",
                                "start_datetime": "2025-04-01T12:57:20.505Z",
                                "end_datetime": "2025-04-01T12:57:20.505Z",
                                "created": "2025-04-01T12:57:20.505Z",
                                "updated": "2025-04-01T12:57:20.505Z",
                                "platform": "string",
                                "instruments": ["string"],
                                "constellation": "string",
                                "mission": "string",
                                "providers": [
                                    {"name": "string", "description": "string", "roles": ["string"], "url": "string"},
                                ],
                                "gsd": 1,
                                "href": "string",
                                "type": "string",
                                "roles": ["string"],
                            },
                        },
                        "links": [
                            {"additionalProp1": "string", "additionalProp2": "string", "additionalProp3": "string"},
                        ],
                        "stac_extensions": ["string"],
                    },
                ],
            },
        },
    },
}
