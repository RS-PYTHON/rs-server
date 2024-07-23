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

"""This library contains all functions needed for the search endpoints."""

import json
from typing import Any, Dict
from urllib.parse import urlencode

from pygeofilter.ast import Attribute, Equal, Like, Node, Union
from pygeofilter.parsers.cql2_json import parse as parse_cql2_json
from pygeofilter.parsers.ecql import parse as parse_ecql
from starlette.requests import Request
from starlette.responses import JSONResponse


def find_owner_id(ecql_ast: Node) -> str:
    """Browse an abstract syntax tree (AST) to find the owner_id.
    Then return it.

    Args:
        ecql_ast (Node): The AST

    Returns:
        str: The owner_id
    """
    res = ""
    if hasattr(ecql_ast, "lhs"):
        if isinstance(ecql_ast.lhs, Attribute) and ecql_ast.lhs.name == "owner":
            if isinstance(ecql_ast, Like):
                res = ecql_ast.pattern
            elif isinstance(ecql_ast, Equal):
                res = ecql_ast.rhs
        elif left := find_owner_id(ecql_ast.lhs):
            res = left
        elif right := find_owner_id(ecql_ast.rhs):
            res = right
    return res


def search_endpoint_get(query: dict[str, list[str]], request: Request) -> Union[str, str, Request]:
    """Endpoint /catalog/search with GET method.

    Args:
        query (dict[str, list[str]]): The search query.
        request (Request): The search request.

    Returns:
        Union[str, str, Request]: Returns the owner_id, the collection_id,
        and the updated request.
    """
    # We have to get the owner_id in the query so we can update de "collections" field.
    qs_filter = query["filter"][0]
    filters = parse_ecql(qs_filter)
    owner_id = find_owner_id(filters)
    collection_id = query["collections"][0]
    if owner_id:
        query["collections"] = [f"{owner_id}_{collection_id}"]
    request.scope["query_string"] = urlencode(query, doseq=True).encode()
    return owner_id, collection_id, request


def search_endpoint_post(content: Dict[str, Any], request: Request) -> Union[str, str, Request]:
    """Endpoint /catalog/search with POST method.

    Args:
        content (json): The request body.
        request (Request): The search request.

    Returns:
        Union[str, str, Request]: Returns the owner_id, the collection_id,
        and the updated request.
    """

    # We have to get the owner_id in the cql2-json query so we can update de "collections" field.
    qs_filter = content["filter"]
    filters = parse_cql2_json(qs_filter)
    owner_id = find_owner_id(filters)
    collection_id = content["collections"][0]
    if owner_id:
        content["collections"] = [f"{owner_id}_{collection_id}"]
    request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access
    return owner_id, collection_id, request


def search_endpoint_in_collection_get(
    query: dict[str, list[str]],
    request: Request,
    owner_id: str,
    collection_id: str,
) -> Request | JSONResponse:
    """Endpoint /catalog/collections/{owner_id}:{collection_id}/search with GET method.

    Args:
        query (dict[str, list[str]]): The search query.
        request (Request): The search request.
        owner_id (str): The owner id.
        collection_id (str): The collection id.


    Returns:
        Request | JSONResponse: Returns the updated request or an error.
    """
    new_query: Dict[str, Any] = {
        "collections": f"{owner_id}_{collection_id}",
        "filter-lang": "cql2-text",
    }
    query.update(new_query)
    request.scope["query_string"] = urlencode(query, doseq=True).encode()
    return request


def search_endpoint_in_collection_post(
    content: Dict[str, Any],
    request: Request,
    owner_id: str,
    collection_id: str | None = None,
) -> Request | JSONResponse:
    """Endpoint /catalog/collections/{owner_id}:{collection_id}/search with POST method.

    Args:
        content (json): The request body.
        request (Request): The search request.
        owner_id (str): The owner id.
        collection_id (str): The collection id.


    Returns:
        Request | JSONResponse: Returns the updated request or an error.
    """
    if "collections" in content:  # If "collections" field exists, just update the existing field.
        content["collections"] = [f"{owner_id}_{collection_id}"]
    else:
        # "collections" field has to be before "filter" field, so we need to create a new dict and insert
        # "collections" field before "filter" field.
        collections = {"collections": [f"{owner_id}_{collection_id}"]}
        content = {**collections, **content}
    request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access
    return request
