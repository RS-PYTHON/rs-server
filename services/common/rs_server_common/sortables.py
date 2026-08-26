# Copyright 2023-2026 CS Group
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

"""Docstring to be added."""

from typing import Any

from stac_fastapi.extensions.sort.client import BaseSortablesClient


class ConfigurableSortablesClient(BaseSortablesClient):
    """STAC Sortables client backed by a configuration dictionary."""

    def __init__(self, properties: dict[str, Any]):
        self.properties = properties

    def get_sortables(
        self,
        request=None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "/sortables",
            "type": "object",
            "title": "Sortables",
            "properties": self.properties,
            "additionalProperties": False,
        }

