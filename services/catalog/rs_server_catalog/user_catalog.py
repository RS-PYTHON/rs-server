"""A BaseHTTPMiddleware to handle the user multi catalog.

The stac-fastapi software doesn't handle multi catalog.
In the rs-server we need to handle user-based catalogs.

The rs-server uses only one catalog but the collections are prefixed by the user name.
The middleware is used to hide this mechanism.

The middleware:
* redirect the user-specific request to the common stac api endpoint
* modifies the request to add the user prefix in the collection name
* modifies the response to remove the user prefix in the collection name
* modifies the response to update the links.
"""

import json
from urllib.parse import parse_qs, urlencode, urlparse

from pygeofilter.ast import Attribute, Equal, Like, Node
from pygeofilter.parsers.cql2_json import parse as parse_cql2_json
from pygeofilter.parsers.ecql import parse as parse_ecql
from rs_server_catalog.user_handler import (
    add_user_prefix,
    filter_collections,
    get_ids,
    remove_user_from_collection,
    remove_user_from_feature,
    remove_user_prefix,
)
from starlette.middleware.base import BaseHTTPMiddleware, StreamingResponse
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class UserCatalogMiddleware(BaseHTTPMiddleware):
    """The user catalog middleware."""

    def remove_user_from_objects(self, content: dict, user: str, object_name: str) -> dict:
        """Remove the user id from the object.

        Args:
            content (dict): The response content from the middleware
            'call_next' loaded in json format.
            user (str): The user id to remove.
            object_name (str): Precise the object type in the content.
            It can be collections or features.

        Returns:
            dict: The content with the user id removed.
        """
        objects = content[object_name]
        nb_objects = len(objects)
        for i in range(nb_objects):
            if object_name == "collections":
                objects[i] = remove_user_from_collection(objects[i], user)
            else:
                objects[i] = remove_user_from_feature(objects[i], user)
        return content

    def adapt_object_links(self, my_object: dict, user: str) -> dict:
        """adapt all the links from a collection so the user can use them correctly

        Args:
            object (dict): The collection
            user (str): The user id

        Returns:
            dict: The collection passed in parameter with adapted links
        """
        links = my_object["links"]
        for j, link in enumerate(links):
            link_parser = urlparse(link["href"])
            if "properties" in my_object:  # If my_object is a feature
                new_path = add_user_prefix(link_parser.path, user, my_object["collection"], my_object["id"])
            else:  # If my_object is a collection
                new_path = add_user_prefix(link_parser.path, user, my_object["id"])
            links[j]["href"] = link_parser._replace(path=new_path).geturl()
        return my_object

    def adapt_links(self, content: dict, user: str, collection_id: str, object_name: str) -> dict:
        """adapt all the links that are outside from the collection section

        Args:
            content (dict): The response content from the middleware
            'call_next' loaded in json format.
            user (str): The user id.

        Returns:
            dict: The content passed in parameter with adapted links
        """
        links = content["links"]
        for i, link in enumerate(links):
            link_parser = urlparse(link["href"])
            new_path = add_user_prefix(link_parser.path, user, collection_id)
            links[i]["href"] = link_parser._replace(path=new_path).geturl()
        for i in range(len(content[object_name])):
            content[object_name][i] = self.adapt_object_links(content[object_name][i], user)
        return content

    def find_owner_id(self, ecql_ast: Node) -> str:
        """Browse an abstract syntax tree (AST) to find the owner_id.
        Then return it.

        Args:
            ecql_ast (_type_): The AST

        Returns:
            str: The owner_id
        """
        res = ""
        if hasattr(ecql_ast, "lhs"):
            if isinstance(ecql_ast.lhs, Attribute) and ecql_ast.lhs.name == "owner_id":
                if isinstance(ecql_ast, Like):
                    res = ecql_ast.pattern
                elif isinstance(ecql_ast, Equal):
                    res = ecql_ast.rhs
            elif left := self.find_owner_id(ecql_ast.lhs):
                res = left
            elif right := self.find_owner_id(ecql_ast.rhs):
                res = right
        return res

    def manage_search_request(self, request: Request) -> Request:
        """find the user in the filter parameter and add it to the
        collection name.

        Args:
            request Request: the client request.

        Returns:
            Request: the new request with the collection name updated.
        """

        query = parse_qs(request.url.query)
        if "filter" in query:
            if "filter-lang" not in query:
                query["filter-lang"] = ["cql2-text"]
            qs_filter = query["filter"][0]
            filters = parse_ecql(qs_filter)
            user = self.find_owner_id(filters)
            if "collections" in query:
                query["collections"] = [f"{user}_{query['collections'][0]}"]
                request.scope["query_string"] = urlencode(query, doseq=True).encode()
        return request

    async def manage_search_response(self, response: StreamingResponse, request: Request) -> Response:
        """The '/catalog/search' endpoint doesn't give the information of the owner_id and collection_id.
        to get these values, this function try to search them into the search query. If successful,
        updates the response content by removing the owner_id from the collection_id and adapt all links.
        If not successful, does nothing and return the response.

        Args:
            response (StreamingResponse): The response from the rs server.
            request (Request): The request from the client.

        Returns:
            Response: The updated response.
        """
        owner_id, collection_id = "", ""
        if request.method == "GET":
            query = parse_qs(request.url.query)
            if "filter" in query:
                qs_filter = query["filter"][0]
                filters = parse_ecql(qs_filter)
        elif request.method == "POST":
            query = await request.json()
            if "filter" in query:
                qs_filter_json = query["filter"]
                filters = parse_cql2_json(qs_filter_json)
        owner_id = self.find_owner_id(filters)
        if "collections" in query:
            collection_id = query["collections"][0].removeprefix(owner_id)
        if owner_id and collection_id:
            body = [chunk async for chunk in response.body_iterator]
            content = json.loads(b"".join(map(lambda x: x if isinstance(x, bytes) else x.encode(), body)).decode())
            content = self.remove_user_from_objects(content, owner_id, "features")
            content = self.adapt_links(content, owner_id, collection_id, "features")
            return JSONResponse(content, status_code=response.status_code)
        return response

    async def manage_put_post_request(self, request: Request, ids: dict) -> Request:
        """Adapt the request body for the STAC endpoint.

        Args:
            request (Request): The Client request to be updated.
            ids (dict): The owner id.

        Returns:
            Request: The request updated.
        """
        user = ids["owner_id"]
        request_body = await request.json()
        if request.scope["path"] == "/collections":  # /catalog/{owner_id}/collections
            request_body["id"] = f"{user}_{request_body['id']}"
        elif (
            f"/collections/{ids['owner_id']}_{ids['collection_id']}/items" in request.scope["path"]
        ):  # /catalog/.../items(/item_id)
            request_body["collection"] = f"{user}_{request_body['collection']}"
        elif request.scope["path"] == "/search" and "filter" in request_body:
            qs_filter = request_body["filter"]
            filters = parse_cql2_json(qs_filter)
            user = self.find_owner_id(filters)
            if "collections" in request_body:
                request_body["collections"] = [f"{user}_{request_body['collections']}"]
        request._body = json.dumps(request_body).encode("utf-8")  # pylint: disable=protected-access
        return request

    async def manage_get_response(
        self,
        request: Request,
        response: StreamingResponse,
        ids: dict,
    ) -> Response:
        """Remove the user name from obects and adapt all links.

        Args:
            request (Request): The client request.
            response (Response | StreamingResponse): The response from the rs-catalog.
            ids (dict): a dictionnary containing owner_id, collection_id and
            item_id if they exist.

        Returns:
            Response: The response updated.
        """
        user = ids["owner_id"]
        body = [chunk async for chunk in response.body_iterator]
        content = json.loads(b"".join(map(lambda x: x if isinstance(x, bytes) else x.encode(), body)).decode())
        if request.scope["path"] == "/":  # /catalog/owner_id
            return JSONResponse(content, status_code=response.status_code)
        if request.scope["path"] == "/collections":  # /catalog/owner_id/collections
            content["collections"] = filter_collections(content["collections"], user)
            content = self.remove_user_from_objects(content, user, "collections")
            content = self.adapt_links(content, ids["owner_id"], ids["collection_id"], "collections")
        elif (
            "/collection" in request.scope["path"] and "items" not in request.scope["path"]
        ):  # /catalog/owner_id/collections/collection_id
            content = remove_user_from_collection(content, user)
            content = self.adapt_object_links(content, user)
        elif (
            "items" in request.scope["path"] and not ids["item_id"]
        ):  # /catalog/owner_id/collections/collection_id/items
            content = self.remove_user_from_objects(content, user, "features")
            content = self.adapt_links(content, ids["owner_id"], ids["collection_id"], "features")
        elif request.scope["path"] == "/search":
            pass
        elif ids["item_id"]:  # /catalog/owner_id/collections/collection_id/items/item_id
            content = remove_user_from_feature(content, user)
            content = self.adapt_object_links(content, user)
        return JSONResponse(content, status_code=response.status_code)

    async def dispatch(self, request, call_next):
        """Redirect the user catalog specific endpoint and adapt the response content."""
        ids = get_ids(request.scope["path"])
        user = ids["owner_id"]
        request.scope["path"] = remove_user_prefix(request.url.path)

        if request.method == "GET" and request.scope["path"] == "/search":
            request = self.manage_search_request(request)
        elif request.method in ["POST", "PUT"] and user:
            request = await self.manage_put_post_request(request, ids)

        response = await call_next(request)

        if request.scope["path"] == "/search":
            response = await self.manage_search_response(response, request)
        elif request.method == "GET" and user:
            response = await self.manage_get_response(request, response, ids)

        return response
