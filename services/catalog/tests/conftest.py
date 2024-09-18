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

"""Common fixture for catalog service."""

import os
import os.path as osp
import subprocess  # nosec ignore security issue
from importlib import reload

RSPY_UAC_HOMEPAGE = "http://RSPY_UAC_HOMEPAGE"
RSPY_UAC_CHECK_URL = "http://RSPY_UAC_CHECK_URL"
OIDC_ENDPOINT = "http://OIDC_ENDPOINT"
OIDC_REALM = "OIDC_REALM"

# Init the FastAPI application with all the cluster mode features (local mode=0).
# Do this before any other imports.
# We'll restore the local mode by default a few lines below.
# pylint: disable=wrong-import-position
# flake8: noqa
os.environ["RSPY_LOCAL_MODE"] = "0"
os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"
os.environ["RSPY_CATALOG_BUCKET"] = "catalog-bucket"
os.environ["RSPY_UAC_HOMEPAGE"] = RSPY_UAC_HOMEPAGE
os.environ["RSPY_UAC_CHECK_URL"] = RSPY_UAC_CHECK_URL
os.environ["OIDC_ENDPOINT"] = OIDC_ENDPOINT
os.environ["OIDC_REALM"] = OIDC_REALM
os.environ["OIDC_CLIENT_ID"] = "OIDC_CLIENT_ID"
os.environ["OIDC_CLIENT_SECRET"] = "OIDC_CLIENT_SECRET"  # nosec
os.environ["RSPY_COOKIE_SECRET"] = "RSPY_COOKIE_SECRET"  # nosec

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from rs_server_catalog.main import app, extract_openapi_specification
from rs_server_common import settings as common_settings
from sqlalchemy_utils import database_exists

# Clean before running.
# No security risks since this file is not released into production.
RESOURCES_FOLDER = Path(osp.realpath(osp.dirname(__file__))) / "resources"
subprocess.run(
    [RESOURCES_FOLDER / "../../../../tests/resources/clean.sh"],
    check=False,
    shell=False,
)  # nosec ignore security issue

app.openapi = extract_openapi_specification
app.openapi()

# Restore the local mode by default
os.environ["RSPY_LOCAL_MODE"] = "1"
reload(common_settings)


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
def docker_compose_file_():
    """Return the path to the docker-compose.yml file to run before tests."""
    return Path(__file__).parent / "docker-compose.yml"


@pytest.mark.integration
@pytest.fixture(scope="session", name="db_url")
def db_url_fixture(docker_ip, docker_services) -> str:  # pylint: disable=missing-function-docstring
    port = docker_services.port_for("stac-db", 5432)
    return f"postgresql://postgres:password@{docker_ip}:{port}/{os.getenv('POSTGRES_DB')}"


@pytest.mark.integration
@pytest.fixture(scope="session", autouse=True, name="start_database")
def start_database_fixture(docker_services, db_url):
    """Ensure pgstac database in available."""
    docker_services.wait_until_responsive(timeout=30.0, pause=0.1, check=lambda: is_db_up(db_url))


@pytest.mark.integration
@pytest.fixture(scope="session", name="client")
def client_fixture(start_database):  # pylint: disable=missing-function-docstring, unused-argument
    # A .env file is read automatically
    # to setup the env to start the app.
    with TestClient(app, follow_redirects=False) as client:
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
            "id": self.name,
            "type": "Collection",
            "owner": self.user,
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


@pytest.fixture(scope="session", name="toto_s1_l1")
def toto_s1_l1_fixture() -> Collection:  # pylint: disable=missing-function-docstring
    return a_collection("toto", "S1_L1")


@pytest.fixture(scope="session", name="toto_s2_l3")
def toto_s2_l3_fixture() -> Collection:  # pylint: disable=missing-function-docstring
    return a_collection("toto", "S2_L3")


@pytest.fixture(scope="session", name="titi_s2_l1")
def titi_s2_l1_fixture() -> Collection:  # pylint: disable=missing-function-docstring
    return a_collection("titi", "S2_L1")


@pytest.fixture(scope="session", name="pyteam_s1_l1")
def pyteam_s1_l1_fixture() -> Collection:  # pylint: disable=missing-function-docstring
    return a_collection("pyteam", "S1_L1")


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


@pytest.fixture(scope="session", name="feature_toto_s1_l1_0")
def feature_toto_s1_l1_0_fixture() -> Feature:  # pylint: disable=missing-function-docstring
    return a_feature("toto", "fe916452-ba6f-4631-9154-c249924a122d", "S1_L1")


@pytest.fixture(scope="session", name="feature_toto_s1_l1_1")
def feature_toto_s1_l1_1_fixture() -> Feature:  # pylint: disable=missing-function-docstring
    return a_feature("toto", "f7f164c9-cfdf-436d-a3f0-69864c38ba2a", "S1_L1")


@pytest.fixture(scope="session", name="feature_titi_s2_l1_0")
def feature_titi_s2_l1_0_fixture() -> Feature:  # pylint: disable=missing-function-docstring
    return a_feature("titi", "fe916452-ba6f-4631-9154-c249924a122d", "S2_L1")


@pytest.fixture(scope="session", name="darius_s1_l2")
def darius_s1_l2_fixture() -> Collection:  # pylint: disable=missing-function-docstring
    return a_collection("darius", "S1_L2")


@pytest.fixture(scope="session", name="feature_pyteam_s1_l1_0")
def feature_pyteam_s1_l1_0_fixture() -> Feature:  # pylint: disable=missing-function-docstring
    return a_feature("pyteam", "hi916451-ca6f-4631-9154-4249924a133d", "S1_L1")


@pytest.fixture(scope="function", name="a_minimal_collection")
def a_minimal_collection_fixture(client) -> Iterator[None]:
    """
    This fixture is used to return the minimal form of accepted collection
    """

    client.post(
        "/catalog/collections",
        json={
            "id": "fixture_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "fixture_owner",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        },
    )

    yield
    # teardown cleanup, delete collection (doesn't matter if it exists or not, so no assertion here)
    client.delete("/catalog/collections/fixture_owner:fixture_collection")


@pytest.fixture(scope="session", name="a_correct_feature")
def a_correct_feature_fixture() -> dict:
    """This fixture returns a correct feature."""
    return {
        "collection": "S1_L2",
        "assets": {
            "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "roles": ["data"],
            },
            "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "roles": ["data"],
            },
            "S1SIWOCN_20220412T054447_0024_S139_T902.nc": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T902.nc",
                "roles": ["data"],
            },
        },
        "bbox": [-180.0, -90.0, 0.0, 180.0, 90.0, 10000.0],
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
        "id": "S1SIWOCN_20220412T054447_0024_S139",
        "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        "other_metadata": {},
        "properties": {
            "gsd": 0.5971642834779395,
            "width": 2500,
            "height": 2500,
            "datetime": "2000-02-02T00:00:00Z",
            "proj:epsg": 3857,
            "orientation": "nadir",
        },
        "stac_extensions": [
            "https://stac-extensions.github.io/eopf/v1.0.0/schema.json",
            "https://stac-extensions.github.io/eo/v1.1.0/schema.json",
            "https://stac-extensions.github.io/sat/v1.0.0/schema.json",
            "https://stac-extensions.github.io/view/v1.0.0/schema.json",
            "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
            "https://stac-extensions.github.io/processing/v1.1.0/schema.json",
        ],
        "stac_version": "1.0.0",
        "type": "Feature",
    }


@pytest.fixture(scope="session", name="a_incorrect_feature")
def a_incorrect_feature_fixture() -> dict:
    """This fixture return a feature without geometry and properties."""
    return {
        "collection": "S1_L2",
        "assets": {
            "S1SIWOCN_20220412T054447_0024_S139_INCORRECT_T717.zarr.zip": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_INCORRECT_T717.zarr.zip",
                "roles": ["data"],
            },
            "S1SIWOCN_20220412T054447_0024_S139_INCORRECT_T420.cog.zip": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_INCORRECT_T420.cog.zip",
                "roles": ["data"],
            },
            "S1SIWOCN_20220412T054447_0024_S139_INCORRECT_T902.nc": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_INCORRECT_T902.nc",
                "roles": ["data"],
            },
        },
        "bbox": [0],
        "geometry": {},
        "id": "S1SIWOCN_20220412T054447_0024_S139_INCORRECT",
        "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        "other_metadata": {},
        "properties": {},
        "stac_extensions": [
            "https://stac-extensions.github.io/eopf/v1.0.0/schema.json",
            "https://stac-extensions.github.io/eo/v1.1.0/schema.json",
            "https://stac-extensions.github.io/sat/v1.0.0/schema.json",
            "https://stac-extensions.github.io/view/v1.0.0/schema.json",
            "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
            "https://stac-extensions.github.io/processing/v1.1.0/schema.json",
        ],
        "stac_version": "1.0.0",
        "type": "Feature",
    }


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


@pytest.mark.integration
@pytest.fixture(scope="session", autouse=True)
def setup_database(
    client,
    toto_s1_l1,
    toto_s2_l3,
    titi_s2_l1,
    darius_s1_l2,
    pyteam_s1_l1,
    feature_toto_s1_l1_0,
    feature_toto_s1_l1_1,
    feature_titi_s2_l1_0,
    feature_pyteam_s1_l1_0,
):  # pylint: disable=missing-function-docstring, too-many-arguments
    """Add collections and feature in the STAC catalog for tests.

    Args:
        client (_type_): The catalog client.
        toto_s1_l1 (_type_): a collection named S1_L1 with the user id toto.
        toto_s2_l3 (_type_): a collection named S2_L3 with the user id toto.
        titi_s2_l1 (_type_): a collection named S2_L1 with the user id titi.
        feature_toto_S1_L1_0 (_type_): a feature from the collection S1_L1 with the
        user id toto.
        feature_toto_S1_L1_1 (_type_): a second feature from the collection S1_L1
        with the user id toto.
        feature_titi_S2_L1_0 (_type_): a feature from the collection S2_L1 with the
        user id titi.
    """
    add_collection(client, toto_s1_l1)
    add_collection(client, toto_s2_l3)
    add_collection(client, titi_s2_l1)
    add_collection(client, darius_s1_l2)
    add_collection(client, pyteam_s1_l1)
    add_feature(client, feature_toto_s1_l1_0)
    add_feature(client, feature_toto_s1_l1_1)
    add_feature(client, feature_titi_s2_l1_0)
    add_feature(client, feature_pyteam_s1_l1_0)
