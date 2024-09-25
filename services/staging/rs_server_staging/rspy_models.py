from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field
from stac_pydantic.shared import Asset  # Importing directly for clarity


class Feature(BaseModel):
    """Custom model for a STAC feature, no restrictions on bbox and links."""

    type: str
    geometry: Optional[dict] = None  # Optional geometry, defaulting to None
    properties: Dict[str, str]
    bbox: Optional[List[Union[int, float]]] = None  # Support both int and float
    id: str
    stac_version: str
    assets: Dict[str, Asset]
    links: Optional[List[Dict[str, str]]] = None
    stac_extensions: List[str]


class RSPYCollectionModel(BaseModel):
    """Model for the collection in the input."""

    title: str
    description: str
    id: str
    schema_: Dict[str, str] = Field(..., alias="schema")  # Use alias for schema field
    minOccurs: int
    maxOccurs: int


class RSPYFeatureCollectionModel(BaseModel):
    """Model for a collection of features."""

    type: str
    features: List[Feature]  # List of Feature models


class RSPYInputModel(BaseModel):
    """Model for input data."""

    collection: RSPYCollectionModel
    items: RSPYFeatureCollectionModel
    provider: str


class RSPYOutputModel(BaseModel):
    title: str
    id: str
    description: str
    schema_: Union[bool, Dict[str, str]] = Field(..., alias="schema")
    minOccurs: int
    maxOccurs: int


class ProcessMetadataModel(BaseModel):
    """Model for process metadata."""

    version: str
    id: str
    title: Dict[str, str]
    description: Dict[str, str]
    jobControlOptions: Union[List[str], str]  # Accept both list and single string
    keywords: List[str]
    links: List[Dict[str, str]]
    inputs: RSPYInputModel
    outputs: Dict[str, RSPYOutputModel]  # Outputs can be of any type, as indicated
