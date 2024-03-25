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
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import botocore
from fastapi import HTTPException
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
from rs_server_common.authentication import apikey_security
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    S3StorageHandler,
    TransferFromS3ToS3Config,
)
from starlette.middleware.base import BaseHTTPMiddleware, StreamingResponse
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

PRESIGNED_URL_EXPIRATION_TIME = 1800  # 30 minutes
bucket_info_path = pathlib.Path(__file__).parent / "config" / "buckets.json"

with open(bucket_info_path, encoding="utf-8") as bucket_info_file:
    bucket_info = json.loads(bucket_info_file.read())


class UserCatalogMiddleware(BaseHTTPMiddleware):
    """The user catalog middleware."""

    handler: S3StorageHandler = None
    temp_bucket_name: str = "temp-bucket"

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

    def clear_temp_bucket(self, content: dict):
        """Used to clear specific files from temporary bucket."""
        if not self.handler:
            return
        for asset in content.get("assets", {}):
            # Iterate through all assets and delete them from the temp bucket.
            file_key = (
                content["assets"][asset]["alternate"]["s3"]["href"]
                .replace(
                    bucket_info["catalog-bucket"]["S3_ENDPOINT"],
                    "",
                )
                .lstrip("/")
            )
            # get the s3 asset file key by removing bucket related info (s3://temp-bucket-key)
            self.handler.delete_file_from_s3(self.temp_bucket_name, file_key)

    def clear_catalog_bucket(self, content: dict):
        """Used to clear specific files from catalog bucket."""
        if not self.handler:
            return
        for asset in content["assets"]:
            # For catalog bucket, data is already store into alternate:s3:href
            file_key = content["assets"][asset]["alternate"]["s3"]["href"]
            self.handler.delete_file_from_s3(bucket_info["catalog-bucket"]["name"], file_key)

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

    def update_stac_item_publication(self, content: dict, user: str) -> Any:  # pylint: disable=too-many-locals
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
                self.temp_bucket_name = old_bucket_arr[0] if "s3" not in old_bucket_arr[0] else old_bucket_arr[2]
                old_bucket_arr[2] = bucket_info["catalog-bucket"]["name"]
                s3_key = "/".join(old_bucket_arr)
                new_s3_href = {"s3": {"href": s3_key}}
                content["assets"][asset].update({"alternate": new_s3_href})
                files_s3_key.append(filename_str.replace(f"s3://{self.temp_bucket_name}", ""))
            except (IndexError, AttributeError, KeyError) as exc:
                raise HTTPException(detail="Invalid obs bucket!", status_code=400) from exc
        # 3 - include new stac extension if not present

        new_stac_extension = "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json"
        if new_stac_extension not in content["stac_extensions"]:
            content["stac_extensions"].append(new_stac_extension)
        # 4 bucket movement
        try:
            if not int(os.environ.get("RSPY_LOCAL_CATALOG_MODE", 0)):  # don't move files if we are in local mode
                self.handler = S3StorageHandler(
                    os.environ["S3_ACCESSKEY"],
                    os.environ["S3_SECRETKEY"],
                    os.environ["S3_ENDPOINT"],
                    os.environ["S3_REGION"],
                )
                config = TransferFromS3ToS3Config(
                    files_s3_key,
                    self.temp_bucket_name,
                    bucket_info["catalog-bucket"]["name"],
                    copy_only=True,
                    max_retries=3,
                )

                failed_files = self.handler.transfer_from_s3_to_s3(config)

                if failed_files:
                    raise HTTPException(
                        detail=f"Could not transfer files to catalog bucket: {failed_files}",
                        status_code=500,
                    )
        except KeyError as kerr:
            raise HTTPException(detail="Could not find S3 credentials", status_code=500) from kerr
        except botocore.exceptions.EndpointConnectionError as exc:
            raise HTTPException(detail="Could not connect to obs bucket!", status_code=400) from exc

        # 5 - add owner data
        content["properties"].update({"owner": user})
        content.update({"collection": f"{user}_{content['collection']}"})
        return content

    def generate_presigned_url(self, content, path):
        """This function is used to generate a time-limited download url"""
        # Assume that pgstac already selected the correct asset id
        # just check type, generate and return url
        asset_id = path.split("/")[-1]
        s3_path = (
            content["assets"][asset_id]["alternate"]["s3"]["href"]
            .replace(
                bucket_info["catalog-bucket"]["S3_ENDPOINT"],
                "",
            )
            .lstrip("/")
        )
        try:
            handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            )
            response = handler.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_info["catalog-bucket"]["name"], "Key": s3_path},
                ExpiresIn=PRESIGNED_URL_EXPIRATION_TIME,
            )
        except KeyError:
            return "Could not find s3 credentials", 400
        except botocore.exceptions.ClientError:
            return "Could not generate presigned url", 400
        return response, 302

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

    async def manage_search_response(self, request: Request, response: StreamingResponse) -> Response:
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

    async def manage_put_post_request(self, request: Request, ids: dict) -> Request | JSONResponse:
        """Adapt the request body for the STAC endpoint.

        Args:
            request (Request): The Client request to be updated.
            ids (dict): The owner id.

        Returns:
            Request: The request updated.
        """
        user = ids["owner_id"]
        try:  # Check if Json is empty or invalid format
            content = await request.json()
        except RuntimeError as exc:
            raise HTTPException(detail="An error occurred while retrieving JSON content", status_code=400) from exc
        if request.scope["path"] == "/collections":
            content["id"] = f"{user}_{content['id']}"
        if "items" in request.scope["path"]:
            content = self.update_stac_item_publication(content, user)
        elif request.scope["path"] == "/search" and "filter" in content:
            qs_filter = content["filter"]
            filters = parse_cql2_json(qs_filter)
            user = self.find_owner_id(filters)
            # May be duplicate?
            if "collections" in content:
                content["collections"] = [f"{user}_{content['collections']}"]
        # update request body (better find the function that updates the body maybe?)c
        request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access
        return request  # pylint: disable=protected-access

    def manage_landing_page(self, request: Request, auth_roles: list, user_login: str, content: dict) -> dict:
        """All sub user catalogs accessible by the user calling it are returned as "child" links.

        Args:
            request (Request): The client request.
            auth_roles (list): list of roles of the api-key.
            user_login (str): The api-key owner.
            content (dict): The landing page.

        Returns:
            dict: The updated landingpage.
        """
        catalog_read_right_pattern = (
            r"rs_catalog_(?P<owner_id>.*(?=:)):(?P<collection_id>.+)_(?P<right_type>read|write|download)(?=$)"
        )
        for role in auth_roles:
            if match := re.match(catalog_read_right_pattern, role):
                groups = match.groupdict()
                if user_login != groups["owner_id"]:
                    child_link = {
                        "rel": "child",
                        "type": "application/json",
                        "href": "",
                    }
                    url = request.url
                    child_link["href"] = f"{url}{groups['owner_id']}"
                    content["links"].append(child_link)
        return content

    def manage_all_collections(self, collections: dict, auth_roles: list, user_login: str) -> dict:
        """Return the list of all collections accessible by the user calling it.

        Args:
            collections (dict): List of all collections.
            auth_roles (list): List of roles of the api-key.
            user_login (str): The api-key owner.

        Returns:
            dict: The list of all collections accessible by the user.
        """
        accessible_collections = []
        catalog_read_right_pattern = (
            r"rs_catalog_(?P<owner_id>.*(?=:)):(?P<collection_id>.+)_(?P<right_type>read|write|download)(?=$)"
        )
        for role in auth_roles:
            if match := re.match(catalog_read_right_pattern, role):
                groups = match.groupdict()
                if groups["right_type"] == "read":  # The user calling the endpoint as read access to:
                    if groups["collection_id"] == "*":  # The user calling the endpoint has access to the entire catalog
                        new_accessible_collections = filter_collections(collections, groups["owner_id"])
                        accessible_collections += new_accessible_collections
                    else:
                        # The user calling the endpoint has access
                        # to a specific collection from the catalog group["owner_id"]
                        new_accessible_collection = filter_collections(
                            collections,
                            f"{groups['owner_id']}_{groups['collection_id']}",
                        )
                        accessible_collections += new_accessible_collection
        accessible_collections += filter_collections(collections, user_login)
        return accessible_collections

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

        if "detail" not in content:  # Test if the user is authenticated.
            if request.scope["path"] == "/":  # /catalog
                try:
                    api_key = request.headers["x-api-key"]
                    auth_roles, _, user_login = await apikey_security(request, api_key)
                    content = self.manage_landing_page(request, auth_roles, user_login, content)
                finally:
                    return JSONResponse(  # pylint: disable=return-in-finally, lost-exception
                        content,
                        status_code=response.status_code,
                    )
            if request.scope["path"] == "/collections":  # /catalog/owner_id/collections
                # ajouter le /collections sans le owner_id
                if ids["owner_id"]:
                    content["collections"] = filter_collections(content["collections"], user)
                    content = self.remove_user_from_objects(content, user, "collections")
                    content = self.adapt_links(content, ids["owner_id"], ids["collection_id"], "collections")
                else:
                    try:
                        api_key = request.headers["x-api-key"]
                        auth_roles, _, user_login = await apikey_security(request, api_key)
                        content["collections"] = self.manage_all_collections(
                            content["collections"],
                            auth_roles,
                            user_login,
                        )
                    finally:
                        pass
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

    async def manage_download_response(self, request: Request, response: StreamingResponse) -> JSONResponse:
        """
        Manage download response and handle requests that should generate a presigned URL.

        Args:
            request (starlette.requests.Request): The request object.
            response (starlette.responses.StreamingResponse): The response object received.

        Returns:
            JSONResponse: Returns a JSONResponse object containing either the presigned URL or
            the response content with the appropriate status code.

        """
        body = [chunk async for chunk in response.body_iterator]
        content = json.loads(b"".join(body).decode())  # type:ignore
        if content.get("code", True) != "NotFoundError":
            # Only generate presigned url if the item is found
            content, code = self.generate_presigned_url(content, request.url.path)
            return JSONResponse(content, status_code=code)
        return JSONResponse(content, status_code=response.status_code)

    async def manage_put_post_response(self, request: Request, response: StreamingResponse, ids: dict):
        """
        Manage put or post responses.

        Args:
            response (starlette.responses.StreamingResponse): The response object received.

        Returns:
            JSONResponse: Returns a JSONResponse object containing the response content
            with the appropriate status code.

        Raises:
            HTTPException: If there is an error while clearing the temporary bucket,
            raises an HTTPException with a status code of 400 and detailed information.
            If there is a generic exception, raises an HTTPException with a status code
            of 400 and a generic bad request detail.

        """
        try:
            body = [chunk async for chunk in response.body_iterator]
            response_content = json.loads(b"".join(body).decode())  # type: ignore
            if request.scope["path"] == "/collections":
                response_content = remove_user_from_collection(response_content, ids["owner_id"])
                response_content = self.adapt_object_links(response_content, ids["owner_id"])
            elif (
                request.scope["path"] == f"/collections/{ids['owner_id']}_{ids['collection_id']}/items/{ids['item_id']}"
            ):
                response_content = remove_user_from_feature(response_content, ids["owner_id"])
                response_content = self.adapt_object_links(response_content, ids["owner_id"])
            self.clear_temp_bucket(response_content)
        except RuntimeError as exc:
            raise HTTPException(detail="Failed to clear temp-bucket", status_code=400) from exc
        except Exception as exc:  # pylint: disable=broad-except
            raise HTTPException(detail="Bad request", status_code=400) from exc
        return JSONResponse(response_content, status_code=response.status_code)

    async def manage_response_error(self, response: StreamingResponse | Any) -> JSONResponse:
        """
        Manage response error when sending a request to the catalog.

        Args:
            response (starlette.responses.StreamingResponse): The response object received from the failed request.

        Raises:
            HTTPException: If the response is not None, clears the catalog bucket and raises an HTTPException
                with a status code of 400 and detailed information about the bad request.
                If the response is None, raises an HTTPException with a status code of 400 and
                a generic bad request detail.

        """
        if response is not None:
            body = [chunk async for chunk in response.body_iterator]
            response_content = json.loads(b"".join(body).decode())  # type:ignore
            self.clear_catalog_bucket(response_content)
            raise HTTPException(detail=f"Bad request, {response_content}", status_code=400)
        # Otherwise just return the exception
        raise HTTPException(detail="Bad request", status_code=400)

    async def manage_delete_response(self, response: StreamingResponse, user: str) -> Response:
        """Change the name of the deleted collection by removing owner_id.

        Args:
            response (StreamingResponse): The client response.
            user (str): The owner id.

        Returns:
            JSONResponse: The new response with the updated collection name.
        """
        body = [chunk async for chunk in response.body_iterator]
        response_content = json.loads(b"".join(body).decode())  # type:ignore
        if "deleted collection" in response_content:
            response_content["deleted collection"] = response_content["deleted collection"].removeprefix(f"{user}_")
        return JSONResponse(response_content)

    async def dispatch(self, request, call_next):
        """Redirect the user catalog specific endpoint and adapt the response content."""
        ids = get_ids(request.scope["path"])
        user = ids["owner_id"]
        request.scope["path"] = remove_user_prefix(request.url.path)

        # Handle requests
        if request.method == "GET" and request.scope["path"] == "/search":
            # URL: GET: '/catalog/search'
            request = self.manage_search_request(request)
        elif request.method in ["POST", "PUT"] and user:
            # URL: POST / PUT: '/catalog/{USER}/collections' or '/catalog/{USER}/collections/{COLLECTION}/items'
            request = await self.manage_put_post_request(request, ids)
        response = None
        try:
            response = await call_next(request)
        except Exception:  # pylint: disable=broad-except
            response = await self.manage_response_error(response)
            return response

        # Handle responses
        if request.scope["path"] == "/search":
            # GET: '/catalog/search'
            response = await self.manage_search_response(request, response)
        elif request.method == "GET" and "download" in request.url.path:
            # URL: GET: '/catalog/{USER}/collections/{COLLECTION}/items/{FEATURE_ID}/download/{ASSET_TYPE}
            response = await self.manage_download_response(request, response)
        elif request.method == "GET" and (user or request.scope["path"] in ["/", "/collections"]):
            # URL: GET: '/catalog/{USER}/Collections'
            # URL: GET: '/catalog'
            # URL: GET: '/catalog/collections
            response = await self.manage_get_response(request, response, ids)
        elif request.method in ["POST", "PUT"] and user:
            # URL: POST / PUT: '/catalog/{USER}/Collections' or '/catalog/{USER}/collections/{COLLECTION}/items'
            response = await self.manage_put_post_response(request, response, ids)
        elif request.method == "DELETE" and user:
            response = await self.manage_delete_response(response, user)

        return response
