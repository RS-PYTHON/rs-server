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

"""Various helpers for tests and tests fixtures."""

import json
import os
import os.path as osp
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient
from sqlalchemy_utils import database_exists

RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / "resources"


def is_db_up(db_url: str) -> bool:
    """Check if the database is up.

    Args:
        db_url: database url

    Returns:
        True if the database is up.
        False otherwise.

    """
    try:
        return database_exists(db_url)
    except ConnectionError:
        return False


def export_aws_credentials():
    """Export AWS credentials as environment variables for testing purposes.

    This function sets the following environment variables with dummy values for AWS credentials:
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_SECURITY_TOKEN
    - AWS_SESSION_TOKEN
    - AWS_DEFAULT_REGION

    Note: This function is intended for testing purposes only, and it should not be used in production.

    Returns:
        None

    Raises:
        None
    """
    with open(RESOURCES_FOLDER / "s3" / "s3.yml", encoding="utf-8") as f:
        s3_config = yaml.safe_load(f)
        os.environ.update(s3_config["s3"])
        os.environ.update(s3_config["boto"])


def clear_aws_credentials():
    """Clear AWS credentials from environment variables."""
    with open(RESOURCES_FOLDER / "s3" / "s3.yml", encoding="utf-8") as f:
        s3_config = yaml.safe_load(f)
        for env_var in list(s3_config["s3"].keys()) + list(s3_config["boto"].keys()):
            del os.environ[env_var]


@dataclass
class Collection:
    """A collection for test purpose."""

    user: str | None
    name: str

    @property
    def id_(self) -> str:
        """Returns the id."""
        return f"{self.user}_{self.name}" if self.user else f"{self.name}"

    @property
    def properties(self) -> dict[str, Any]:
        """Returns the properties."""
        properites = {
            "id": self.name,
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": f"http://localhost:8082/collections/{self.name}/items",
                },
                {"rel": "parent", "type": "application/json", "href": "http://localhost:8082/"},
                {"rel": "root", "type": "application/json", "href": "http://localhost:8082/"},
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": f"""http://localhost:8082/collections/{self.name}""",
                },
                {
                    "rel": "license",
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "title": "public domain",
                },
            ],
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
            "license": "public-domain",
            "description": "Some description",
            "stac_version": "1.0.0",
        }
        if self.user:
            properites["owner"] = self.user

        return properites


def a_collection(user: str | None, name: str) -> Collection:
    """Create a collection for test purpose.

    The collection is built from a prototype.
    Only the id varies from a collection to another.
    The id is built with the given user and name : user_name

    Args:
        user: the collection owner
        name: the collection name

    Returns: the initialized collection

    """
    return Collection(user, name)


def add_collection(client: TestClient, collection: Collection):
    """Add the given collection in the STAC catalog.

    Args:
        client: the catalog client
        collection: the collection to add

    Returns:
        None

    Raises:
        Error if the collection addition failed.
    """
    response = client.post(
        "/catalog/collections",
        json=collection.properties,
    )
    response.raise_for_status()


def add_collection_from_dict(client: TestClient, collection: dict) -> tuple[str, str]:
    """
    Adds a collection in the STAC catalog unless it already exists.

    Args:
        client: the catalog client
        collection: the collection to add

    Returns:
        None

    Raises:
        Error if the collection addition failed.
    """
    collection_check = client.get(f"/catalog/collections/{collection['owner']}:{collection['id']}/items")
    if collection_check.status_code == 404:
        response = client.post("/catalog/collections", json=collection)
        response.raise_for_status()
    return (collection["owner"], collection["id"])


@dataclass
class Feature:
    """A feature for test purpose."""

    owner_id: str
    id_: str
    collection: str

    @property
    def properties(self) -> dict[str, Any]:  # pylint: disable=missing-function-docstring
        return {
            "id": self.id_,
            "bbox": [-94.6334839, 37.0332547, -94.6005249, 37.0595608],
            "type": "Feature",
            "assets": {
                "may24C355000e4102500n.tif": {
                    "href": f"""s3://temp-bucket/{self.collection}/images/may24C355000e4102500n.tif""",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "title": "NOAA STORM COG",
                },
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-94.6334839, 37.0595608],
                        [-94.6334839, 37.0332547],
                        [-94.6005249, 37.0332547],
                        [-94.6005249, 37.0595608],
                        [-94.6334839, 37.0595608],
                    ],
                ],
            },
            "collection": f"{self.collection}",
            "properties": {
                "gsd": 0.5971642834779395,
                "width": 2500,
                "height": 2500,
                "datetime": "2000-02-02T00:00:00Z",
                "proj:epsg": 3857,
                "orientation": "nadir",
                "owner_id": f"{self.owner_id}",
            },
            "stac_version": "1.0.0",
            "stac_extensions": [
                "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
                "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
            ],
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        }


def a_feature(owner_id: str, id_: str, in_collection: str) -> Feature:
    """Create a feature for test purpose.

    The feature is built from a prototype.
    Only the feature id and the parent collection is stored are configurable.

    Args:
        id_: the feature id
        in_collection: the collection id containing the feature

    Returns:
        The initialized feature
    """
    return Feature(owner_id, id_, in_collection)


def add_feature(client: TestClient, feature: Feature):
    """Add the given feature in the STAC catalogue.

    Args:
        client (TestClient): The catalog client.
        feature (Feature): The feature to add.
    """
    response = client.post(
        f"/catalog/collections/{feature.owner_id}:{feature.collection}/items",
        json=feature.properties,
    )
    response.raise_for_status()


def add_feature_from_dict(client: TestClient, feature: dict) -> tuple[str, str]:
    """Add the given feature in the STAC catalogue.

    Args:
        client (TestClient): The catalog client.
        feature (dict): The feature to add.
    """
    owner_id = feature["properties"]["owner"]
    collection = feature["collection"]

    # Check if collection exists, if not then add it
    collection_to_create = build_minimal_collection_from_feature_data(feature)
    add_collection_from_dict(client, collection_to_create)

    # Check if item exists, if not add it
    item_check = client.get(f"/catalog/collections/{owner_id}:{collection}/items/{feature['id']}").status_code
    if item_check == 404:
        response = client.post(
            f"/catalog/collections/{owner_id}:{collection}/items",
            json=feature,
        )
        response.raise_for_status()

    return (owner_id, collection)


def build_minimal_collection_from_feature_data(feature: dict) -> dict:
    """
    Creates a basic collection definition matching the given feature.

    Args:
        feature (dict): The feature used to create the collection.
    """

    return {
        "id": feature["collection"],
        "type": "Collection",
        "description": "Auto-generated collection for tests purposes",
        "stac_version": feature["stac_version"] if "stac_version" in feature.keys() else "1.0.0",
        "owner": (
            feature["properties"]["owner"]
            if "properties" in feature.keys() and "owner" in feature["properties"].keys()
            else "unknown"
        ),
        "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        "license": "public-domain",
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [["2000-01-01T00:00:00Z", "2100-01-01T00:00:00Z"]]},
        },
    }


def add_features_from_file(client: TestClient, collection_file_name: str) -> tuple[str, str]:
    """Reads a collection from the given file and adds it to the STAC catalog.

    Args:
        client: the catalog client
        collection_file_name: name of the file containing the collection to add.
            This file must be in the resources folder.

    Returns:
        None

    Raises:
        Error if the collection addition failed.
    """
    collection_file = Path.joinpath(RESOURCES_FOLDER, collection_file_name)
    collection_owner = ""
    collection_name = ""
    with open(collection_file, encoding="utf-8") as json_file:
        collection = json.load(json_file)

    # 1st case: ONE feature
    if isinstance(collection, dict) and "type" in collection.keys() and collection["type"] == "Feature":
        (collection_owner, collection_name) = add_feature_from_dict(client, collection)

    # 2nd case: a list of features
    if isinstance(collection, dict) and "features" in collection.keys():
        collection = collection["features"]

    if isinstance(collection, list):
        for feature in collection:
            (collection_owner, collection_name) = add_feature_from_dict(client, feature)

    return (collection_owner, collection_name)


def delete_collection(client: TestClient, collection_owner: str, collection_name: str):
    """Deletes the collection linked to the given owner and name

    Args:
        client: the catalog client
        collection_owner: name of the owner of the collection
        collection_name: name of the collection

    Returns:
        None

    """
    client.delete(f"/catalog/collections/{collection_owner}:{collection_name}")
