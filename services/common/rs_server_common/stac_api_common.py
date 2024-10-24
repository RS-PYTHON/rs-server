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
import abc
import copy
import json
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Callable,
    List,
    Literal,
    Optional,
    Self,
    Type,
    Union,
)

import stac_pydantic
import stac_pydantic.links
import yaml
from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError
from rs_server_common import settings
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    extract_eo_product,
    odata_to_stac,
    validate_inputs_format,
)

logger = Logging.default(__name__)


class Queryables(BaseModel):
    """
    BaseModel used to describe queryable holder.
    See: site-packages/pypgstac/migrations/pgstac.0.8.6.sql
    """

    id: str = Field("", alias="$id")
    type: str = Field("object")
    title: str = Field("STAC Queryables.")
    schema: str = Field("http://json-schema.org/draft-07/schema#", alias="$schema")  # type: ignore
    properties: dict[str, Any] = Field({})

    class Config:  # pylint: disable=too-few-public-methods
        """Used to overwrite BaseModel config and display aliases in model_dump."""

        allow_population_by_field_name = True


class QueryableField(BaseModel):
    """BaseModel used to describe queryable item."""

    type: str
    title: str
    format: Optional[str] = None
    pattern: Optional[str] = None
    description: Optional[str] = None
    enum: Optional[List[str]] = None


@dataclass
class MockPgstac:
    """
    Mock a pgstac database for the services (adgs, cadip, ...) that use stac_fastapi but don't need a database.
    """

    # Set by stac-fastapi
    request: Request | None = None
    readwrite: Literal["r", "w"] | None = None

    # adgs, cadip, ...
    service: str

    # adgs or cadip function
    all_collections: Callable = None
    select_config: Callable = None
    get_queryables: Callable = None
    stac_to_odata: Callable = None
    map_mission: Callable = None

    @classmethod
    @asynccontextmanager
    async def get_connection(cls, request: Request, readwrite: Literal["r", "w"] = "r") -> AsyncIterator[Self]:
        """Return a class instance"""
        yield cls(request, readwrite)

    @dataclass
    class ReadPool:
        """Used to mock the readpool function."""

        # Outer MockPgstac class type
        outer_cls: Type["MockPgstac"]

        @asynccontextmanager
        async def acquire(self) -> AsyncIterator[Self]:
            """Return an outer class instance"""
            yield self.outer_cls()

    @classmethod
    def readpool(cls):
        """Mock the readpool function."""
        return cls.ReadPool(cls)

    async def fetchval(self, query, *args, column=0, timeout=None):
        """Run a query and return a value in the first row.

        :param str query: Query text.
        :param args: Query arguments.
        :param int column: Numeric index within the record of the value to
                           return (defaults to 0).
        :param float timeout: Optional timeout value in seconds.
                            If not specified, defaults to the value of
                            ``command_timeout`` argument to the ``Connection``
                            instance constructor.

        :return: The value of the specified column of the first record, or
                 None if no records were returned by the query.
        """
        query = query.strip()

        # From stac_fastapi.pgstac.core.CoreCrudClient::all_collections
        if query == "SELECT * FROM all_collections();":
            return filter_allowed_collections(self.all_collections(), self.service, self.request)

        # From stac_fastapi.pgstac.core.CoreCrudClient::get_collection
        if query == "SELECT * FROM get_collection($1::text);":

            # Find the collection which id == the input collection_id
            collection_id = args[0]
            collection = self.select_config(collection_id)
            if not collection:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown {self.service} collection: {collection_id!r}")

            # Convert into stac object (to ensure validity) then back to dict
            collection.setdefault("stac_version", "1.0.0")
            return create_collection(collection).model_dump()

        # from stac_fastapi.pgstac.extensions.filter.FiltersClient::get_queryables
        # args[0] contains the collection_id, if any.
        if query == "SELECT * FROM get_queryables($1::text);":
            return Queryables(properties=self.get_queryables(args[0] if args else None)).model_dump(by_alias=True)

        # from stac_fastapi.pgstac.core.CoreCrudClient::_search_base
        if query == "SELECT * FROM search($1::text::jsonb);":
            params = json.loads(args[0]) if args else {}
            return await self.search(self.request, params)

        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"Not implemented PostgreSQL query: {query!r}")

    @abc.abstractmethod
    async def read_search_params(self, params: dict, stac_params: dict):
        """Child specific search parameter reading."""

    async def search(self, params: dict) -> stac_pydantic.ItemCollection:
        """
        Search products using filters coming from the STAC FastAPI PgSTAC /search endpoints.
        """

        #
        # Step 1: read input params

        # Input params will be converted into stac params
        stac_params = {}

        # Call the child method
        await self.read_search_params(params, stac_params)

        def format_dict(field: dict):
            """Used for error handling."""
            return json.dumps(field, indent=0).replace("\n", "").replace('"', "'")

        # Number of results per page
        limit = params.pop("limit", None)

        # Sort results
        sortby_list = params.pop("sortby", [])
        if len(sortby_list) > 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Only one 'sortby' search parameter is allowed: {sortby_list!r}",
            )
        if not sortby_list:
            sortby = ""
        else:
            sortby_dict = sortby_list[0]
            sortby = "+" if sortby_dict["direction"] == "asc" else "-"
            sortby += sortby_dict["field"]

        # Collections to search
        collection_ids = params.pop("collections", [])

        # datetime interval = PublicationDate
        datetime = params.pop("datetime", None)
        if datetime:
            try:
                validate_inputs_format(datetime, raise_errors=True)
                stac_params["published"] = datetime
            except HTTPException as exception:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Invalid datetime interval: {datetime!r}. "
                    "Expected format is: 'YYYY-MM-DDThh:mm:ssZ/YYYY-MM-DDThh:mm:ssZ'",
                ) from exception

        #
        # Read query and/or CQL filter

        # Only the queryable properties are allowed
        allowed_properties = self.get_queryables().keys()

        def read_property(property: str, value: Any):
            """Read a query or CQL filter property"""
            nonlocal stac_params
            if True or not property in allowed_properties:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Invalid query or CQL property: {property!r}, " f"allowed properties are: {allowed_properties}",
                )
            stac_params[property] = value

        def read_cql(filter: dict):
            """Use a recursive function to read all CQL filter levels"""
            if not filter:
                return
            op = filter.get("op")
            args = filter.get("args", [])

            # Read a single property
            if op == "=":
                if (len(args) != 2) or not (property := args[0].get("property")):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"Invalid CQL2 filter: {format_dict(filter)}",
                    )
                value = args[1]
                return read_property(property, value)

            # Else we are reading several properties
            elif op != "and":
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Invalid CQL2 filter, only '=' and 'and' operators are allowed: {format_dict(filter)}",
                )
            for sub_filter in args:
                read_cql(sub_filter)

        read_cql(params.pop("filter", {}))

        # Read the query
        query = params.pop("query", {})
        for property, operator in query.items():
            if (len(operator) != 1) or not (value := operator.get("eq")):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Invalid query: {{{property!r}: {format_dict(operator)}}}"
                    ", only {'<property>': {'eq': <value>}} is allowed",
                )
            read_property(property, value)

        # Discard these search parameters
        params.pop("conf", None)
        params.pop("filter-lang", None)

        # Discard the "fields" parameter only if its "include" and "exclude" properties are empty
        fields = params.get("fields", {})
        if not fields.get("include") and not fields.get("exclude"):
            params.pop("fields", None)

        # If search parameters remain, they are not implemented
        if params:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unimplemented search parameters: {format_dict(params)}",
            )

        #
        # Step 2: do the search

        # map stac platform/constellation to odata satellite... which is called "platform" in the stac standard.
        stac_params["platform"] = self.map_mission(stac_params.get("platform"), stac_params.get("constellation"))

        # Convert them from STAC keys to OData keys
        user_odata = self.stac_to_odata(stac_params)

        # Only keep the authorized collections
        allowed = filter_allowed_collections(self.all_collections(), self.service, self.request)
        allowed_ids = set(collection["id"] for collection in allowed)
        if not collection_ids:
            collection_ids = allowed_ids
        else:
            collection_ids = allowed_ids.intersection(collection_ids)

        # Items for all collections
        all_items = stac_pydantic.ItemCollection(features=[], type="FeatureCollection")

        first_exception = None

        # For each collection to search
        for collection_id in collection_ids:
            try:

                # Some OData search params are defined in the collection configuration.
                collection = self.select_config(collection_id)
                collection_odata = collection.get("query", {})

                # The final params to use come from the collection (higher priority) and the user
                odata = {**user_odata, **collection_odata}

                # Overwrite the pagination parameters
                odata["top"] = limit or odata.get("top") or 20  # default = 20 results per page

                # Do the search for this collection
                items: stac_pydantic.ItemCollection = process_session_search(
                    self.request,
                    collection.get("station", "cadip"),
                    odata.get("SessionId"),
                    odata.get("Satellite"),
                    odata.get("PublicationDate"),
                    odata.get("top"),
                )

                # Add the collection information
                for item in items.features:
                    item.collection = collection_id

                # Concatenate items for all collections
                all_items.features.extend(items.features)

            except Exception as exception:
                logger.error(traceback.format_exc())
                first_exception = first_exception or exception

        # If there are no results and we had at least one exception, raise the first one
        if not all_items.features and first_exception:
            raise first_exception

        # Return results as a dict
        return all_items.model_dump()


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
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
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


def filter_allowed_collections(all_collections, role, request):
    """Filters collections based on user roles and permissions.

    This function returns only the collections that a user is allowed to read based on their
    assigned roles in KeyCloak. If the application is running in local mode, all collections
    are returned without filtering.

    Parameters:
        all_collections (list[dict]): A list of all available collections, where each collection
                                       is represented as a dictionary.
        role (str): The role of the user requesting access to the collections, which is used to
                    build the required authorization key for filtering collections.
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

    # Foreach allowed collection, create links and append to response.
    stac_collections = []
    for config in filtered_collections:
        config.setdefault("stac_version", "1.0.0")
        try:
            collection: stac_pydantic.Collection = create_collection(config)
            stac_collections.append(collection.model_dump())

        # If a collection is incomplete in the configuration file, log the error and proceed
        except HTTPException as exception:
            if exception.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
                logger.error(exception)
            else:
                raise
    return stac_collections


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
