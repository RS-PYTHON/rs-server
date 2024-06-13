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

from typing import Dict, List

import eodag
import starlette.requests

DEFAULT_GEOM = {"geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))"}


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
    asset["href"] = f'{str(request.url).split("session", maxsplit=1)[0]}cadu?name={asset.pop("id")}'
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
        session["assets"] = [
            map_dag_file_to_asset(mapper, product, request)
            for product in input_session
            if product.properties["SessionID"] == session["id"]
        ]
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
