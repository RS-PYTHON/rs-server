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