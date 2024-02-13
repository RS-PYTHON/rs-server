"""Common fixture for catalog service."""

from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy_utils import database_exists
from starlette.testclient import TestClient

from rs_server_catalog.main import app

import os.path as osp


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


@pytest.fixture(scope="session", name="docker_compose_file")
def docker_compose_file_(pytestconfig):
    """Return the path to the docker-compose.yml file to run before tests."""
    return osp.join(str(pytestconfig.rootdir), "rs-server", "services", "catalog", "tests", "docker-compose.yml")


@pytest.mark.integration
@pytest.fixture(scope="session")
def db_url(docker_ip, docker_services) -> str:
    port = docker_services.port_for("stac-db", 5432)
    return f"postgresql://postgres:password@{docker_ip}:{port}/rspy"


@pytest.mark.integration
@pytest.fixture(scope="session", autouse=True)
def start_database(docker_services, db_url):
    """Ensure pgstac database in available."""
    docker_services.wait_until_responsive(timeout=30.0, pause=0.1, check=lambda: is_db_up(db_url))


@pytest.mark.integration
@pytest.fixture(scope="session")
def client(start_database):
    # A .env file is read automatically
    # to setup the env to start the app.
    with TestClient(app) as client:
        yield client


@dataclass
class Collection:
    """A collection for test purpose."""

    user: str
    name: str

    @property
    def id_(self) -> str:
        """Returns the id."""
        return f"{self.user}_{self.name}"

    @property
    def properties(self) -> dict[str, Any]:
        """Returns the properties."""
        return {
            "id": self.id_,
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": f"http://localhost:8082/collections/{self.id_}/items",
                },
                {"rel": "parent", "type": "application/json", "href": "http://localhost:8082/"},
                {"rel": "root", "type": "application/json", "href": "http://localhost:8082/"},
                {"rel": "self", "type": "application/json", "href": f"http://localhost:8082/collections/{self.id_}"},
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


def a_collection(user: str, name: str) -> Collection:
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


@pytest.fixture(scope="session")
def toto_s1_l1() -> Collection:
    return a_collection("toto", "S1_L1")


@pytest.fixture(scope="session")
def toto_s2_l3() -> Collection:
    return a_collection("toto", "S2_L3")


@pytest.fixture(scope="session")
def titi_s2_l1() -> Collection:
    return a_collection("titi", "S2_L1")


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
        f"/catalog/{collection.user}/collections",
        json=collection.properties,
    )
    response.raise_for_status()


@dataclass
class Feature:
    """A feature for test purpose."""

    id_: str
    collection: str
    properties: dict[str, Any]


def a_feature(id_: str, in_collection: str) -> Feature:
    """Create a feature for test purpose.

    The feature is built from a prototype.
    Only the feature id and the parent collection is stored are configurable.

    Args:
        id_: the feature id
        in_collection: the collection id containing the feature

    Returns:
        The initialized feature
    """
    properties = {
        "id": id_,
        "bbox": [-94.6334839, 37.0332547, -94.6005249, 37.0595608],
        "type": "Feature",
        "links": [
            {
                "rel": "collection",
                "type": "application/json",
                "href": f"http://localhost:8082/collections/{in_collection}",
            },
            {"rel": "parent", "type": "application/json", "href": f"http://localhost:8082/collections/{in_collection}"},
            {"rel": "root", "type": "application/json", "href": "http://localhost:8082/"},
            {
                "rel": "self",
                "type": "application/geo+json",
                "href": f"http://localhost:8082/collections/{in_collection}/items/{id_}",
            },
        ],
        "assets": {
            "COG": {
                "href": "https://arturo-stac-api-test-data.s3.amazonaws.com/joplin/images/may24C355000e4102500n.tif",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "title": "NOAA STORM COG",
            }
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
                ]
            ],
        },
        "collection": in_collection,
        "properties": {
            "gsd": 0.5971642834779395,
            "width": 2500,
            "height": 2500,
            "datetime": "2000-02-02T00:00:00Z",
            "proj:epsg": 3857,
            "orientation": "nadir",
        },
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
            "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
        ],
    }
    return Feature(id_, in_collection, properties)
