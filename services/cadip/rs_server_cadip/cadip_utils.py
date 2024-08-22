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

"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""

import os
import os.path as osp
from pathlib import Path
from typing import Dict, List

import eodag
import starlette.requests
import yaml

DEFAULT_GEOM = {"geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))"}
CADIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "config"
search_yaml = CADIP_CONFIG / "cadip_search_config.yaml"


def validate_cadip_config(fp):
    """Function to validate yaml template, tba. Should we check this?"""
    accepted_stations = ["cadip", "ins", "mts"]  # pylint: disable=unused-variable # noqa
    accepted_queries = [  # pylint: disable=unused-variable # noqa
        "id",
        "platform",
        "datetime",
        "start_date",
        "stop_date",
        "limit",
        "sortby",
    ]
    # Check that yaml content for query and stations (for now) is in accepted list.
    return fp


def read_conf():
    """Used each time to read RSPY_CADIP_SEARCH_CONFIG config yaml."""
    cadip_search_config = validate_cadip_config(os.environ.get("RSPY_CADIP_SEARCH_CONFIG", str(search_yaml.absolute())))
    with open(cadip_search_config, encoding="utf-8") as search_conf:
        config = yaml.safe_load(search_conf)
    return config


def select_config(configuration_id: str) -> dict | None:
    """Used to select a specific configuration from yaml file, returns None if not found."""
    return next(
        (item for item in read_conf()["collections"] if item["id"] == configuration_id),
        None,
    )


def rename_keys(product: dict) -> dict:
    """Rename keys in the product dictionary. To match eodag specific properties key name (id / startTime..)"""
    if "Id" in product:
        product["id"] = product.pop("Id")
    if "PublicationDate" in product:
        product["startTimeFromAscendingNode"] = product["PublicationDate"]
    return product


def update_product(product: dict) -> dict:
    """Update product with renamed keys and default geometry."""
    product = rename_keys(product)
    product.update(DEFAULT_GEOM)
    return product


def map_dag_file_to_asset(mapper: dict, product: eodag.EOProduct, request: starlette.requests.Request):
    """This function is used to map extended files from odata to stac format."""
    asset = {map_key: product.properties[map_value] for map_key, map_value in mapper.items()}
    asset["roles"] = ["cadu"]
    asset["href"] = f'http://{request.url.netloc}/cadip/cadu?name={asset.pop("id")}'
    return {product.properties["Name"]: asset}


def from_session_expand_to_dag_serializer(input_sessions: List[eodag.EOProduct]) -> List[eodag.EOProduct]:
    """
    Convert a list of sessions containing expanded files metadata into a list of files for serialization into the DB.
    """
    return [
        eodag.EOProduct(provider="internal_session_product_file_from_cadip", properties=update_product(product))
        for session in input_sessions
        for product in session.properties.get("Files", [])
    ]


def from_session_expand_to_assets_serializer(
    feature_collection,
    input_session: eodag.EOProduct,
    mapper: dict,
    request: starlette.requests.Request,
) -> Dict:
    """
    Associate all expanded files with session from feature_collection and create an asset for each file.
    """
    for session in feature_collection["features"]:
        # Initialize an empty dictionary for the session's assets
        session["assets"] = {}

        # Iterate over products and map them to assets
        for product in input_session:
            if product.properties["SessionID"] == session["id"]:
                # Get the asset dictionary
                asset_dict = map_dag_file_to_asset(mapper, product, request)

                # Merge the asset dictionary into session['assets']
                session["assets"].update(asset_dict)

        # Remove processed products from input_session
        input_session = [product for product in input_session if product.properties["SessionID"] != session["id"]]

    return feature_collection


def validate_products(products: eodag.EOProduct):
    """Function used to remove all miconfigured outputs."""
    valid_eo_products = []
    for product in products:
        try:
            str(product)
            valid_eo_products.append(product)
        except eodag.utils.exceptions.MisconfiguredError:
            continue
    return valid_eo_products
