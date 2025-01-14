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

"""
Module used to overwrite stac_pydantic with RSPY types.
"""

# mypy: ignore-errors
from typing import Optional, Sequence

import stac_pydantic
from geojson_pydantic import FeatureCollection
from pydantic import ConfigDict, Field
from stac_pydantic.links import Links
from stac_pydantic.shared import StacBaseModel, StacCommonMetadata


class WrapStacCommonMetadata(StacCommonMetadata):
    """
    Custom implementation of pydantic.StacCommonMetadata
    Overload stac_pydantic datetime-like objects from item properties to use a string with custom format.
    Datetime only use microseconds ".512000Z", so this model is updated to store a more flexible date type.
    """

    datetime: Optional[str] = Field(...)
    created: Optional[str] = None
    updated: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None


class ItemProperties(WrapStacCommonMetadata):
    """
    Custom implementation of stac_pydantic.ItemProperties
    """

    model_config = ConfigDict(extra="allow")


class Item(stac_pydantic.item.Item):
    """
    Custom implementation of stac_pydantic.Item.
    """

    properties: ItemProperties


class ItemCollection(FeatureCollection, StacBaseModel):
    """
    Custom implementation of stac_pydantic.ItemCollection.
    """

    features: Sequence[Item]
    links: Optional[Links] = None
