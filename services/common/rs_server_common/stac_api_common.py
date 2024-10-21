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

"""Module to share common functionalities for validating / creating stac items"""
import copy
from functools import wraps
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

import stac_pydantic
import stac_pydantic.links
import yaml
from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from rs_server_common import settings
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import extract_eo_product, odata_to_stac

logger = Logging.default(__name__)


class Queryables(BaseModel):
    """BaseModel used to describe queryable holder."""

    schema: str = Field("https://json-schema.org/draft/2019-09/schema", alias="$schema")  # type: ignore
    id: str = Field("https://stac-api.example.com/queryables", alias="$id")
    type: str
    title: str
    description: str
    properties: dict[str, Any]

    class Config:  # pylint: disable=too-few-public-methods
        """Used to overwrite BaseModel config and display aliases in model_dump."""

        allow_population_by_field_name = True


class RSPYQueryableField(BaseModel):
    """BaseModel used to describe queryable item."""

    title: str
    type: str
    description: Optional[str] = None
    format: Optional[str] = None
    items: Optional[dict] = None


def create_links(products: List[Any], provider):
    """Used to create stac_pydantic Link objects based on sessions lists."""
    if provider == "CADIP":
        return [
            stac_pydantic.links.Link(rel="item", title=product.properties["SessionId"], href="./simple-item.json")
            for product in products
        ]
    return [
        stac_pydantic.links.Link(rel="item", title=product.properties["Name"], href="./simple-item.json")
        for product in products
    ]


def create_collection(collection: dict) -> stac_pydantic.Collection:
    """Used to create stac_pydantic Model Collection based on given collection data."""
    try:
        stac_collection = stac_pydantic.Collection(type="Collection", **collection)
        return stac_collection
    except ValidationError as exc:
        raise HTTPException(
            detail=f"Unable to create stac_pydantic.Collection, {repr(exc.errors())}",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc


def handle_exceptions(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator used to wrapp all endpoints that can raise KeyErrors / ValidationErrors while creating/validating
    items."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except KeyError as exc:
            logger.error(f"KeyError caught in {func.__name__}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Cannot create STAC Collection -> Missing {exc}",
            ) from exc
        except ValidationError as exc:
            logger.error(f"ValidationError caught in {func.__name__}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Parameters validation error: {exc}",
            ) from exc

    return wrapper


def filter_allowed_collections(all_collections, role, collection_search_func, request):
    """Filters collections based on user roles and permissions.

    This function returns only the collections that a user is allowed to read based on their
    assigned roles in KeyCloak. If the application is running in local mode, all collections
    are returned without filtering.

    Parameters:
        all_collections (list[dict]): A list of all available collections, where each collection
                                       is represented as a dictionary.
        role (str): The role of the user requesting access to the collections, which is used to
                    build the required authorization key for filtering collections.
        collection_search_func (Callable): A function that takes a collection configuration
                                            and returns query parameters for searching that
                                            collection.
        request (Request): The request object, which contains user authentication roles
                           available through `request.state.auth_roles`.

    Returns:
        dict: A JSON object containing the type, links, and a list of filtered collections
              that the user is allowed to access. The structure of the returned object is
              as follows:
              - type (str): The type of the STAC object, which is always "Object".
              - links (list): A list of links associated with the STAC object (currently empty).
              - collections (list[dict]): A list of filtered collections, where each collection
                                           is a dictionary representation of a STAC collection.

    Logging:
        Debug-level logging is used to log the IDs of collections the user is allowed to
        access and the query parameters generated for each allowed collection. Errors during
        collection creation are also logged.

    Raises:
        HTTPException: If a collection configuration is incomplete or invalid, an
                       HTTPException is raised with status code 422. Other exceptions
                       are propagated as-is.
    """
    # No authentication: select all collections
    if settings.LOCAL_MODE:
        filtered_collections = all_collections

    else:
        # Read the user roles defined in KeyCloak
        try:
            auth_roles = request.state.auth_roles or []
        except AttributeError:
            auth_roles = []

        # Only keep the collections that are associated to a station that the user has access to
        filtered_collections = [
            collection for collection in all_collections if f"rs_{role}_{collection['station']}_read" in auth_roles
        ]

    logger.debug(f"User allowed collections: {[collection['id'] for collection in filtered_collections]}")
    # Create JSON object.
    stac_object: dict = {"type": "Object", "links": [], "collections": []}

    # Foreach allowed collection, create links and append to response.
    for config in filtered_collections:

        config.setdefault("stac_version", "1.0.0")

        query_params = collection_search_func(config)
        logger.debug(f"Collection {config['id']} params: {query_params}")

        try:
            collection: stac_pydantic.Collection = create_collection(config)
            stac_object["collections"].append(collection.model_dump())

        # If a collection is incomplete in the configuration file, log the error and proceed
        except HTTPException as exception:
            if exception.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
                logger.error(exception)
            else:
                raise
    return stac_object


def map_stac_platform() -> Union[str, List[str]]:
    """Function used to read and interpret from constellation.yaml"""
    with open(Path(__file__).parent.parent / "config" / "constellation.yaml", encoding="utf-8") as cf:
        return yaml.safe_load(cf)


def create_stac_collection(
    products: List[Any],
    feature_template: dict,
    stac_mapper: dict,
) -> stac_pydantic.ItemCollection:
    """
    Creates a STAC feature collection based on a given template for a list of EOProducts.

    Args:
        products (List[EOProduct]): A list of EOProducts to create STAC features for.
        feature_template (dict): The template for generating STAC features.
        stac_mapper (dict): The mapping dictionary for converting EOProduct data to STAC properties.

    Returns:
        dict: The STAC feature collection containing features for each EOProduct.
    """
    items: list = []

    for product in products:
        product_data = extract_eo_product(product, stac_mapper)
        feature_tmp = odata_to_stac(copy.deepcopy(feature_template), product_data, stac_mapper)
        item = stac_pydantic.Item(**feature_tmp)
        items.append(item)
    return stac_pydantic.ItemCollection(features=items, type="FeatureCollection")


def sort_feature_collection(feature_collection: dict, sortby: str) -> dict:
    """
    Sorts a STAC feature collection based on a given criteria.

    Args:
        feature_collection (dict): The STAC feature collection to be sorted.
        sortby (str): The sorting criteria. Use "+fieldName" for ascending order
            or "-fieldName" for descending order. Use "+doNotSort" to skip sorting.

    Returns:
        dict: The sorted STAC feature collection.

    Note:
        If sortby is not in the format of "+fieldName" or "-fieldName",
        the function defaults to ascending order by the "datetime" field.
    """
    # Force default sorting even if the input is invalid, don't block the return collection because of sorting.
    if sortby != "+doNotSort":
        order = sortby[0]
        if order not in ["+", "-"]:
            order = "+"

        if len(feature_collection["features"]) and "properties" in feature_collection["features"][0]:
            field = sortby[1:]
            by = "datetime" if field not in feature_collection["features"][0]["properties"].keys() else field
            feature_collection["features"] = sorted(
                feature_collection["features"],
                key=lambda feature: feature["properties"][by],
                reverse=order == "-",
            )
    return feature_collection


def generate_queryables(config: dict, queryables_handler: Callable) -> dict[str, RSPYQueryableField]:
    """Function used to get available queryables based on a given collection."""
    if config:
        # Top and limit are pagination-related quaryables, remove if there.
        if isinstance(config.get("query"), dict):
            config["query"].pop("limit", None)
            config["query"].pop("top", None)
        # Get all defined quaryables.
        all_queryables = queryables_handler()
        # Remove the ones already defined, and keep only the ones that can be added.
        for key in set(config["query"].keys()).intersection(set(all_queryables.keys())):
            all_queryables.pop(key)
        return all_queryables
    # If config is not found, return all available queryables.
    return queryables_handler()
