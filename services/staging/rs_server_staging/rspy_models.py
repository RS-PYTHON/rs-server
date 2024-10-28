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
"""Module used to type-check input of rs-staging."""

from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field  # pylint: disable=no-name-in-module
from stac_pydantic.shared import Asset  # Importing directly for clarity


# pylint: disable=too-few-public-methods
# pylint: disable= no-name-in-module
class Feature(BaseModel):
    """Custom model for a STAC (SpatioTemporal Asset Catalog) feature.

    This model defines a STAC feature without restrictions on the bounding box (`bbox`)
    and links. It is designed to store geographic and metadata information about a
    specific feature.

    Attributes:
        type (str): The type of the feature (e.g., "Feature").
        geometry (Optional[dict]): The geometry of the feature, represented as a
            dictionary (e.g., GeoJSON). Defaults to None.
        properties (Dict[str, str]): A dictionary of feature properties, where keys
            represent property names and values are the corresponding values.
        bbox (Optional[List[Union[int, float]]]): A bounding box defining the feature's
            spatial extent. It supports both integer and float values. Defaults to None.
        id (str): The unique identifier for the feature.
        stac_version (str): The version of the STAC specification used.
        assets (Dict[str, Asset]): A dictionary of assets associated with the feature.
            Keys are asset names, and values are `Asset` objects.
        links (Optional[List[Dict[str, str]]]): A list of link dictionaries, where each
            dictionary represents a link related to the feature. Defaults to None.
        stac_extensions (List[str]): A list of STAC extension URIs used in this feature.
    """

    type: str
    geometry: Optional[dict] = None
    properties: Dict[str, str]
    bbox: Optional[List[Union[int, float]]] = None
    id: str
    stac_version: str
    assets: Dict[str, Asset]
    links: Optional[List[Dict[str, str]]] = None
    stac_extensions: List[str]


class CollectionModel(BaseModel):
    """Model representing a collection in the input data.

    This model describes a collection with metadata such as title, description, and
    a schema definition. It also defines occurrence constraints (`minOccurs` and
    `maxOccurs`) for the collection.

    Attributes:
        title (str): The title of the collection.
        description (str): A brief description of the collection.
        id (str): The unique identifier for the collection.
        schema_ (Dict[str, str]): A dictionary representing the schema of the collection.
            This field is aliased as "schema".
        minOccurs (int): The minimum number of occurrences of items in the collection.
        maxOccurs (int): The maximum number of occurrences of items in the collection.
    """

    title: str
    description: str
    id: str
    schema_: Dict[str, str] = Field(..., alias="schema")
    minOccurs: int
    maxOccurs: int


class FeatureCollectionModel(BaseModel):
    """Model representing a collection of features.

    This model is used to group multiple `Feature` objects into a single collection.

    Attributes:
        type (str): The type of the feature collection (e.g., "FeatureCollection").
        features (List[Feature]): A list of `Feature` objects included in the collection.
    """

    type: str
    features: List[Feature]


class InputModel(BaseModel):
    """Model for input data.

    This model encapsulates the input information, including a collection of features,
    metadata, and the provider.

    Attributes:
        collection (CollectionModel): The collection of metadata for the input.
        items (FeatureCollectionModel): A collection of features related to the input.
        provider (str): The name or identifier of the data provider.
    """

    collection: CollectionModel
    items: FeatureCollectionModel
    provider: str


class OutputModel(BaseModel):
    """Model representing output data metadata.

    This model describes the metadata associated with output data, including schema
    definition and occurrence constraints.

    Attributes:
        title (str): The title of the output data.
        id (str): The unique identifier for the output.
        description (str): A description of the output data.
        schema_ (Union[bool, Dict[str, str]]): The schema definition for the output
            data, which could either be a boolean or a dictionary. This field is
            aliased as "schema".
        minOccurs (int): The minimum number of occurrences for the output data.
        maxOccurs (int): The maximum number of occurrences for the output data.
    """

    title: str
    id: str
    description: str
    schema_: Union[bool, Dict[str, str]] = Field(..., alias="schema")
    minOccurs: int
    maxOccurs: int


class ProcessMetadataModel(BaseModel):
    """Model for process metadata.

    This model describes metadata for a process, including version information,
    inputs, outputs, and associated links.

    Attributes:
        version (str): The version of the process.
        id (str): The unique identifier for the process.
        title (Dict[str, str]): A dictionary containing the title of the process,
            potentially in multiple languages.
        description (Dict[str, str]): A dictionary containing the description of
            the process, potentially in multiple languages.
        jobControlOptions (Union[List[str], str]): A list or single string defining
            the job control options available for the process.
        keywords (List[str]): A list of keywords related to the process.
        links (List[Dict[str, str]]): A list of dictionaries representing related links.
        inputs (InputModel): The inputs required for the process.
        outputs (Dict[str, OutputModel]): A dictionary representing the outputs
            of the process, where keys are output names and values are `OutputModel`
            objects.
    """

    version: str
    id: str
    title: Dict[str, str]
    description: Dict[str, str]
    jobControlOptions: Union[List[str], str]
    keywords: List[str]
    links: List[Dict[str, str]]
    inputs: InputModel
    outputs: Dict[str, OutputModel]
