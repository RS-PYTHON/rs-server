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

"""Sortables extension for RS-Server."""

from typing import Any

from stac_fastapi.extensions.sort.client import BaseSortablesClient


class RSSortablesClient(BaseSortablesClient):
    """Sortables exposed by RS-Server."""

    SCHEMA_URL = "https://json-schema.org/draft/2020-12/schema"
    SCHEMA_TITLE = "Sortables"
    SORTABLES_BASE_URL = "https://example.org"

    COMMON_PROPERTIES = {
        "id": {
            "title": "Identifier",
            "type": "string",
        },
        "file:size": {
            "title": "File size",
            "type": "number",
        },
        "type": {
            "title": "Type",
            "type": "string",
        },
        "eviction_datetime": {
            "title": "Eviction datetime",
            "type": "string",
            "format": "date-time",
        },
        "created": {
            "title": "Created",
            "type": "string",
            "format": "date-time",
        },
        "start_datetime": {
            "title": "Start datetime",
            "type": "string",
            "format": "date-time",
        },
        "end_datetime": {
            "title": "End datetime",
            "type": "string",
            "format": "date-time",
        },
    }

    PROPERTIES = {
        "cadip": {
            "id": {
                "title": "Identifier",
                "type": "string",
            },
            "datetime": {
                "title": "Datetime",
                "type": "string",
                "format": "date-time",
            },
            "published": {
                "title": "Published",
                "type": "string",
                "format": "date-time",
            },
        },
        "auxip": {
            **COMMON_PROPERTIES,
        },
        "prip": {
            **COMMON_PROPERTIES,
            "published": {
                "title": "Published",
                "type": "string",
                "format": "date-time",
            },
        },
    }

    def __init__(self, router_prefix: str):
        self.router_prefix = router_prefix.strip("/")

    def _build_schema(self, path: str) -> dict[str, Any]:
        """Build a Sortables JSON Schema."""
        return {
            "$id": f"{self.SORTABLES_BASE_URL}/{path}",
            "$schema": self.SCHEMA_URL,
            "type": "object",
            "title": self.SCHEMA_TITLE,
            "properties": self.PROPERTIES.get(self.router_prefix, {}),
        }

    # pylint: disable = unused-argument
    def get_sortables(
        self,
        request=None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return sortables for the /search endpoint."""
        return self._build_schema(
            f"{self.router_prefix}/sortables",
        )

    # pylint: disable = unused-argument
    def get_collection_sortables(
        self,
        collection_id: str,
        request=None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Return sortables for the /collections/{collection_id}/items endpoint."""
        return self._build_schema(
            f"{self.router_prefix}/collections/{collection_id}/sortables",
        )
