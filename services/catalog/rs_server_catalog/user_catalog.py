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
import os
import pathlib
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import botocore
import starlette
from pygeofilter.ast import Attribute, Equal, Like, Node
from pygeofilter.parsers.ecql import parse as parse_ecql
from rs_server_catalog.user_handler import (
    add_user_prefix,
    filter_collections,
    get_ids,
    remove_user_from_collection,
    remove_user_from_feature,
    remove_user_prefix,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3StorageHandler,
    TransferFromS3ToS3Config,
)
from starlette.middleware.base import BaseHTTPMiddleware, StreamingResponse
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

bucket_info_path = pathlib.Path(__file__).parent / "config" / "buckets.json"

with open(bucket_info_path, encoding="utf-8") as bucket_info_file:
    bucket_info = json.loads(bucket_info_file.read())


def clear_temp_bucket(handler, content: dict):
    """Used to clear specific files from temporary bucket."""
    if not handler:
        return
    for asset in content["assets"]:
        # Iterate through all assets and delete them from the temp bucket.
        file_key = content["assets"][asset]["alternate"]["s3"]["href"].replace(
            bucket_info["catalog-bucket"]["S3_ENDPOINT"],
            "",
        )
        # get the s3 asset file key by removing bucket related info (s3://temp-bucket-key)
        handler.delete_file_from_s3(bucket_info["temp-bucket"]["name"], file_key)


def clear_catalog_bucket(handler, content: dict):
    """Used to clear specific files from catalog bucket."""
    if not handler:
        return
    for asset in content["assets"]:
        # For catalog bucket, data is already store into alternate:s3:href
        file_key = content["assets"][asset]["alternate"]["s3"]["href"]
        handler.delete_file_from_s3(bucket_info["catalog-bucket"]["name"], file_key)


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

    @staticmethod
    def update_stac_item_publication(content: dict, user: str) -> Any:  # pylint: disable=too-many-locals
        """Update json body of feature push to catalog"""
        files_s3_key = []
        # 1 - update assets href
        for asset in content["assets"]:
            filename_str = content["assets"][asset]["href"]
            fid = filename_str.rsplit("/", maxsplit=1)[-1]
            new_href = (
                f'https://rs-server/catalog/{user}/collections/{content["collection"]}/items/{fid}/download/{asset}'
            )
            content["assets"][asset].update({"href": new_href})
            # 2 - update alternate href to define catalog s3 bucket
            try:
                old_bucket_arr = filename_str.split("/")
                old_bucket_arr[2] = bucket_info["catalog-bucket"]["name"]
                s3_key = "/".join(old_bucket_arr)
                new_s3_href = {"s3": {"href": s3_key}}
                content["assets"][asset].update({"alternate": new_s3_href})
                files_s3_key.append(filename_str.replace(bucket_info["temp-bucket"]["S3_ENDPOINT"], ""))
            except (IndexError, AttributeError, KeyError):
                return JSONResponse("Invalid obs bucket!", status_code=400), None
        # 3 - include new stac extension if not present

        new_stac_extension = "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json"
        if new_stac_extension not in content["stac_extensions"]:
            content["stac_extensions"].append(new_stac_extension)
        # 4 tdb, bucket movement
        handler = None
        try:
            # try with env, but maybe read from json file?
            handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            )
            config = TransferFromS3ToS3Config(
                files_s3_key,
                bucket_info["temp-bucket"]["name"],
                bucket_info["catalog-bucket"]["name"],
                copy_only=True,
                max_retries=3,
            )
            failed_files = handler.transfer_from_s3_to_s3(config)
            if failed_files:
                return JSONResponse(f"Could not transfer files to catalog bucket: {failed_files}", status_code=500)

        except KeyError:
            pass
            # JSONResponse("Could not find S3 credentials", status_code=500)
        except botocore.exceptions.EndpointConnectionError:
            return JSONResponse("Could not connect to obs bucket!", status_code=400)

        # 5 - add owner data
        content["properties"].update({"owner": user})
        content.update({"collection": f"{user}_{content['collection']}"})
        return content, handler

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

    def manage_search_endpoint(self, request: Request) -> Request:
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

    async def manage_put_post_endpoints(self, request: Request, ids: dict) -> Request:
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
        request._body = json.dumps(request_body).encode("utf-8")  # pylint: disable=protected-access
        return request

    async def manage_get_endpoints(
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
        elif ids["item_id"]:  # /catalog/owner_id/collections/collection_id/items/item_id
            content = remove_user_from_feature(content, user)
            content = self.adapt_object_links(content, user)
        return JSONResponse(content, status_code=response.status_code)

    async def dispatch(self, request, call_next):  # pylint: disable=too-many-return-statements
        """Redirect the user catalog specific endpoint and adapt the response content."""
        s3_handler = None
        ids = get_ids(request.scope["path"])
        user = ids["owner_id"]
        request.scope["path"] = remove_user_prefix(request.url.path)

        if request.method in ["POST", "PUT"] and user:
            content = await request.body()
            content = json.loads(content.decode("utf-8"))
            if request.scope["path"] == "/collections":
                content["id"] = f"{user}_{content['id']}"
            if "items" in request.scope["path"]:
                content, s3_handler = UserCatalogMiddleware.update_stac_item_publication(content, user)
                # If something fails inside update_stac_item_publication don't forward the request
                if isinstance(content, starlette.responses.JSONResponse):
                    return JSONResponse(content.body.decode(), status_code=content.status_code)
                # update request body (better find the function that updates the body maybe?)
            request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access
            # Send updated request and return updated content response
            response = None
            try:
                response = await call_next(request)
            except Exception as e:  # pylint: disable=broad-except
                # If something fails while publishing data into catalog, revert files moved into catalog bucket
                if response is not None:
                    # Capture response content from catalog, if any
                    clear_catalog_bucket(s3_handler, content)
                    body = [chunk async for chunk in response.body_iterator]
                    response_content = json.loads(b"".join(body).decode())
                    return JSONResponse(f"Bad request, {response_content}, {e}", status_code=400)
                # Otherwise just return the exception
                return JSONResponse(f"Bad request, {e}", status_code=400)
            # If catalog publication is successful, remove files from temp bucket
            clear_temp_bucket(s3_handler, content)
            return JSONResponse(content, status_code=response.status_code)
        # Handle GET requests
        if request.method == "GET" and request.scope["path"] == "/search":
            request = self.manage_search_endpoint(request)
        elif request.method in ["POST", "PUT"] and user:
            request = await self.manage_put_post_endpoints(request, ids)

        response = await call_next(request)
        if request.method == "GET" and user:
            response = await self.manage_get_endpoints(request, response, ids)

        return response
