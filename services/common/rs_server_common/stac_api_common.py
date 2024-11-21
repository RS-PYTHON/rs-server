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
import json
import traceback
import urllib.parse
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Self,
    Type,
)

import stac_pydantic
import stac_pydantic.links
import yaml
from fastapi import HTTPException, Request, status
from fastapi.datastructures import QueryParams
from pydantic import BaseModel, Field, ValidationError
from rs_server_common import settings
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    extract_eo_product,
    odata_to_stac,
    validate_inputs_format,
)
from stac_pydantic.item import Item

# pylint: disable=attribute-defined-outside-init
logger = Logging.default(__name__)

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


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
class MockPgstac(ABC):  # pylint: disable=too-many-instance-attributes
    """
    Mock a pgstac database for the services (adgs, cadip, ...) that use stac_fastapi but don't need a database.
    """

    # Set by stac-fastapi
    request: Request | None = None
    readwrite: Literal["r", "w"] | None = None

    service: Literal["adgs", "cadip"] | None = None

    # adgs or cadip function
    all_collections: Callable = lambda: None
    select_config: Callable = lambda: None
    stac_to_odata: Callable = lambda: None
    map_mission: Callable = lambda: None

    # Is the service adgs or cadip ?
    adgs: bool = False
    cadip: bool = False

    # Current page
    page: int = 1

    # Number of results per page
    limit: int | None = None

    def __post_init__(self):
        self.adgs = self.service in ("adgs", "auxip")
        self.cadip = self.service == "cadip"

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
        async def acquire(self) -> AsyncIterator["MockPgstac"]:
            """Return an outer class instance"""
            yield self.outer_cls()

    @classmethod
    def readpool(cls):
        """Mock the readpool function."""
        return cls.ReadPool(cls)

    def get_queryables(self, collection_id: str | None = None) -> dict[str, QueryableField]:
        """Function to list all available queryables for CADIP session search."""

        # Note: the queryables contain stac keys
        queryables = {}

        # If the collection has a product type field hard-coded with a single value,
        # the user cannot query on it.
        # TODO: factorize this code for all query parameters.
        if self.adgs:
            can_query = True
            if collection_id:
                value = self.select_config(collection_id).get("query", {}).get("productType", "")
                if value and ("," not in value):
                    can_query = False
            if can_query:
                queryables["product:type"] = QueryableField(
                    type="string",
                    title="productType",
                    format="string",
                    description="String",
                )

        # Idem for satellite or platform
        can_query = True
        if collection_id:
            for field in "platformSerialIdentifier", "platformShortName", "Satellite":
                value = self.select_config(collection_id).get("query", {}).get(field, "")
                if value and ("," not in value):
                    can_query = False
                    break

        # Read all platforms and constellations from the configuration file
        if can_query:
            config = {}
            for satellite in map_stac_platform().get("satellites", {}):
                config.update(satellite)
            platforms = sorted(set(config.keys()))
            connstellations = sorted(
                {platform["constellation"] for platform in config.values() if "constellation" in platform},
            )
            queryables.update(
                {
                    "platform": QueryableField(
                        type="string",
                        title="platform",
                        format="string",
                        description="String",
                        enum=platforms,
                    ),
                    "constellation": QueryableField(
                        type="string",
                        title="constellation",
                        format="string",
                        description="String",
                        enum=connstellations,
                    ),
                },
            )

        return queryables

    async def fetchval(self, query, *args, column=0, timeout=None):  # pylint: disable=unused-argument
        """Run a query and return a value in the first row.

        Args:
            query (str): Query text.
            args: Query arguments.
            column (int): Numeric index within the record of the value to return (defaults to 0).
            timeout (timeout): Optional timeout value in seconds. If not specified, defaults to the value of
            ``command_timeout`` argument to the ``Connection`` instance constructor.

        Returns: The value of the specified column of the first record,
        or None if no records were returned by the query.
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
            return Queryables(properties=self.get_queryables(args[0] if args else None)).model_dump(  # type: ignore
                by_alias=True,
            )

        # from stac_fastapi.pgstac.core.CoreCrudClient::_search_base
        if query == "SELECT * FROM search($1::text::jsonb);":
            params = json.loads(args[0]) if args else {}
            return await self.search(params)

        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, f"Not implemented PostgreSQL query: {query!r}")

    async def search(  # pylint: disable=too-many-branches, too-many-statements, too-many-locals
        self,
        params: dict,
    ) -> dict[str, Any]:
        """
        Search products using filters coming from the STAC FastAPI PgSTAC /search endpoints.
        """
        if self.request is None:
            raise AssertionError("Request should be defined")

        #
        # Step 1: read input params

        stac_params = {}

        def format_dict(field: dict):
            """Used for error handling."""
            return json.dumps(field, indent=0).replace("\n", "").replace('"', "'")

        # Read the pagination query parameters from the GET or POST request URL.
        # They can be set either as standard parameters or as "token" parameters.
        # The token values have higher priority.
        for as_token in [False, True]:
            query_params: dict | QueryParams = self.request.query_params
            if as_token:
                token = query_params.get("token")  # for GET
                if not token:
                    try:
                        token = (await self.request.json()).get("token")  # for POST
                    except json.JSONDecodeError:
                        pass
                if not token:
                    continue

                # Remove the prev: or next: prefix and parse the string
                token = token.removeprefix("prev:").removeprefix("next:")
                query_params = urllib.parse.parse_qs(token)

            # Merge pagination parameters into input params.
            # Convert lists with one element into this single value.
            for key, values in query_params.items():
                if key not in ("limit", "page", "sort"):
                    continue
                if isinstance(values, list) and (len(values) == 1):
                    params[key] = values[0]
                else:
                    params[key] = values

        # Collections to search
        collection_ids = [collection.strip() for collection in params.pop("collections", [])]

        # IDs to search
        ids = params.pop("ids", None)

        # The cadip session ids are set in parameter or in the request state
        # by the /collections/{collection_id}/items/{session_id} endpoint
        if self.cadip:
            if not ids:
                try:
                    ids = self.request.state.session_id
                except AttributeError:
                    pass

        # Save the auxip product names or cadip session ids
        if isinstance(ids, list):
            stac_params["id"] = [id.strip() for id in ids]
        elif isinstance(ids, str):
            stac_params["id"] = ids.strip()  # type: ignore

        # Page number
        page = params.pop("page", None)
        if page:
            try:
                self.page = int(page)
                if self.page < 1:
                    raise ValueError
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid page value: {page!r}",
                ) from exc

        # Number of results per page
        limit = params.pop("limit", None)
        if limit:
            try:
                self.limit = int(limit)
                if self.limit < 1:
                    raise ValueError
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid limit value: {limit!r}",
                ) from exc

        # Sort results
        sortby = "-datetime"  # default value
        sortby_list = params.pop("sortby", [])
        if len(sortby_list) > 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Only one 'sortby' search parameter is allowed: {sortby_list!r}",
            )
        if sortby_list:
            sortby_dict = sortby_list[0]
            sortby = "+" if sortby_dict["direction"] == "asc" else "-"
            sortby += sortby_dict["field"]

        # datetime interval = PublicationDate
        datetime = params.pop("datetime", None)
        if datetime:
            try:
                validate_inputs_format(datetime, raise_errors=True)
                if self.adgs:
                    stac_params["created"] = datetime
                elif self.cadip:
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
        allowed_properties = sorted(self.get_queryables().keys())

        def read_property(prop: str, value: Any):
            """Read a query or CQL filter property"""
            nonlocal stac_params
            if prop not in allowed_properties:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Invalid query or CQL property: {prop!r}, " f"allowed properties are: {allowed_properties}",
                )
            if isinstance(value, dict):
                value = value.get("property")
            if isinstance(value, str):
                value = value.strip()
            stac_params[prop] = value

        def read_cql(filt: dict):
            """Use a recursive function to read all CQL filter levels"""
            if not filt:
                return
            op = filt.get("op")
            args = filt.get("args", [])

            # Read a single property
            if op == "=":
                if (len(args) != 2) or not (prop := args[0].get("property")):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_ENTITY,
                        f"Invalid CQL2 filter: {format_dict(filt)}",
                    )
                value = args[1]
                read_property(prop, value)
                return

            # Else we are reading several properties
            if op != "and":
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Invalid CQL2 filter, only '=' and 'and' operators are allowed: {format_dict(filt)}",
                )
            for sub_filter in args:
                read_cql(sub_filter)

        read_cql(params.pop("filter", {}))

        # Read the query
        query = params.pop("query", {})
        for prop, operator in query.items():
            if (len(operator) != 1) or not (value := operator.get("eq")):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Invalid query: {{{prop!r}: {format_dict(operator)}}}"
                    ", only {'<property>': {'eq': <value>}} is allowed",
                )
            read_property(prop, value)

        # map stac platform/constellation values to odata values...
        mission = self.map_mission(stac_params.get("platform"), stac_params.get("constellation"))
        # ... still saved with stac keys for now
        if self.adgs:
            stac_params["constellation"], stac_params["platform"] = mission
        if self.cadip:
            stac_params["platform"] = mission

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

        # Convert search params from STAC keys to OData keys
        odata_params = self.stac_to_odata(stac_params)

        # Only keep the authorized collections
        allowed = filter_allowed_collections(self.all_collections(), self.service, self.request)
        allowed_ids = set(collection["id"] for collection in allowed)
        if not collection_ids:
            collection_ids = list(allowed_ids)
        else:
            collection_ids = list(allowed_ids.intersection(collection_ids))

        # Item features for all collections.
        # Use a dict ordered by ID so we only keep unique items, based on their ID.
        all_features: Dict[str, Item] = {}

        first_exception = None

        # For each collection to search
        for collection_id in collection_ids:  # pylint: disable=too-many-nested-blocks
            try:

                # Some OData search params are hardcoded in the collection configuration.
                collection = self.select_config(collection_id)
                odata_hardcoded = collection.get("query") or {}

                # Merge the user input params with the hardcoded params (which have higher priority)
                self.odata = {**odata_params, **odata_hardcoded}

                empty_selection = False

                # Handle conflicts, i.e. for each key that is defined in both params
                for key in set(odata_params.keys()).intersection(odata_hardcoded.keys()):

                    # Date intervals
                    if key in ("PublicationDate"):

                        # Read both start and stop dates
                        start1, stop1 = validate_inputs_format(odata_params[key], raise_errors=True)
                        start2, stop2 = validate_inputs_format(odata_hardcoded[key], raise_errors=True)

                        # Calculate the intersection
                        start = max(start1, start2)
                        stop = min(stop1, stop2)

                        # If no intersection, then the selection is empty, else save the intersection
                        if start >= stop:
                            empty_selection = True
                            break  # try next collection
                        self.odata[key] = f"{start.strftime(DATETIME_FORMAT)}/{stop.strftime(DATETIME_FORMAT)}"

                    # Comma-separated lists
                    if key in ("platformSerialIdentifier", "platformShortName", "Satellite", "productType"):

                        # Read both values
                        value1 = odata_params[key]
                        value2 = odata_hardcoded[key]
                        intersection = None

                        # If one is empty or None, this means "keep everything".
                        # So keep the intersection = the other list.
                        if not value1:
                            intersection = value2
                        elif not value2:
                            intersection = value1

                        # Else, split by comma and keep the intersection.
                        # If no intersection, then the selection is empty.
                        else:
                            for i, value in enumerate((value1, value2)):
                                s = {v.strip() for v in value.split(",")}
                                intersection = intersection.intersection(s) if i else s  # type: ignore
                            if intersection:
                                intersection = ", ".join(intersection)
                            if not intersection:
                                empty_selection = True
                                break  # try next collection

                        # Save the intersection
                        self.odata[key] = intersection

                # If the selection is empty, we return no items for this collection
                if empty_selection:
                    continue  # try next collection

                # Overwrite the pagination parameters.
                # User-defined 'limit' value has higher priority over the collection hardcoded 'top' value
                if not self.limit:
                    self.limit = self.odata.get("top", 1000)

                # TODO: what to do with the sortby parameter ?

                # Do the search for this collection
                features = (await self.process_search(collection, self.odata)).features

                # Add the collection information
                for item in features:
                    item.collection = collection_id

                # Concatenate features for all collections, ordered by their ID
                all_features.update({item.id: item for item in features})

            except Exception as exception:  # pylint: disable=broad-exception-caught
                logger.error(traceback.format_exc())
                first_exception = first_exception or exception

        # If there are no results and we had at least one exception, raise the first one
        if not all_features and first_exception:
            raise first_exception

        # Return results as a dict
        data = stac_pydantic.ItemCollection(features=list(all_features.values()), type="FeatureCollection").model_dump()

        # Handle pagination links.
        data["next"] = f"page={self.page + 1}"
        if self.page > 1:
            data["prev"] = f"page={self.page - 1}"

        return data

    @abstractmethod
    async def process_search(self, collection: dict, odata_params: dict) -> stac_pydantic.ItemCollection:
        """Do the search for the given collection and OData parameters."""


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


def map_stac_platform() -> dict:
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
        # Add a default bbox and geometry, since L0 chunks items are not geo-located.
        item.bbox = (-180.0, -90.0, 180.0, 90.0)
        item.geometry = {
            "type": "Polygon",
            "coordinates": [[[-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]]],
        }
        item.stac_extensions = [str(se) for se in item.stac_extensions]  # type: ignore
        items.append(item)
    return stac_pydantic.ItemCollection(features=items, type="FeatureCollection")
