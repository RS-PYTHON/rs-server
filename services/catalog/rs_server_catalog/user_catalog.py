"""A BaseHTTPMiddleware to handle the user multi catalog.

The stac-fastapi software doesn't handle multi catalog.
In the rs-server we need to handle user-based catalogs.

The rs-server uses only one catalog but the collections are prefixed by the user name.
The middleware is used to hide this mechanism.

The middleware:
* redirect the user-specific request to the common stac api endpoint
* modifies the response to remove the user prefix in the collection name
* modifies the response to update the links.
"""

import json
import os
import pathlib
from typing import Any
from urllib.parse import urlparse

import botocore.exceptions
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
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

PRESIGNED_URL_EXPIRATION_TIME = 1800  # 30 minutes
bucket_info_path = pathlib.Path(__file__).parent / "config" / "buckets.json"

with open(bucket_info_path, encoding="utf-8") as bucket_info_file:
    bucket_info = json.loads(bucket_info_file.read())


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
            # Note, conversion to pathlib.Path removes the double / from s3://bucket/path/to/file
            filename = pathlib.Path(content["assets"][asset]["href"])
            fid = str(filename).rsplit("/", maxsplit=1)[-1]
            new_href = (
                f'https://rs-server/catalog/{user}/collections/{content["collection"]}/items/{fid}/download/{asset}'
            )
            content["assets"][asset].update({"href": new_href})
            # 2 - update alternate href to define catalog s3 bucket
            s3_key = filename_str.replace(
                bucket_info["temp-bucket"]["S3_ENDPOINT"],
                bucket_info["catalog-bucket"]["S3_ENDPOINT"],
            )
            new_s3_href = {"s3": {"href": s3_key}}
            content["assets"][asset].update({"alternate": new_s3_href})
            files_s3_key.append(filename_str.replace(bucket_info["temp-bucket"]["S3_ENDPOINT"], ""))
        # 3 - include new stac extension if not present

        new_stac_extension = "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json"
        if new_stac_extension not in content["stac_extensions"]:
            content["stac_extensions"].append(new_stac_extension)
        # 4 tdb, bucket movement
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
                max_retries=3,
            )
            failed_files = handler.transfer_from_s3_to_s3(config)
            if failed_files:
                return JSONResponse(f"Could not transfer files to catalog bucket: {failed_files}", status_code=500)

        except KeyError:
            # JSONResponse("Could not find S3 credentials", status_code=500)
            error = ("Could not find S3 credentials", 500)  # pylint: disable=unused-variable # noqa

        # 5 - add owner data
        content["owner"] = user
        content.update({"collection": f"{user}_{content['collection']}"})
        return content

    def generate_presigned_url(self, content, path):
        """This function is used to generate a time-limited download url"""
        # Assume that pgstac already selected the correct asset id
        # just check type, generate and return url
        asset_id = path.split("/")[-1]
        s3_path = content["assets"][asset_id]["alternate"]["s3"]["href"].replace(
            bucket_info["catalog-bucket"]["S3_ENDPOINT"],
            "",
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
            return "Could not find s3 credentials"
        except botocore.exceptions.ClientError:
            return "Could not generate presigned url"
        return response, 302

    async def dispatch(self, request, call_next):
        """Redirect the user catalog specific endpoint and adapt the response content."""

        ids = get_ids(request.scope["path"])
        user = ids["owner_id"]
        request.scope["path"] = remove_user_prefix(request.url.path)

        if request.method in ["POST", "PUT"] and user:
            content = await request.body()
            content = json.loads(content.decode("utf-8"))
            if request.scope["path"] == "/collections":
                content["id"] = f"{user}_{content['id']}"
            if "items" in request.scope["path"]:
                content = UserCatalogMiddleware.update_stac_item_publication(content, user)
                # update request body (better find the function that updates the body maybe?)
            request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access
            # Send updated request and return updated content response
            try:
                response = await call_next(request)
            except Exception as e:  # pylint: disable=broad-except
                return JSONResponse(f"Bad request, {e}", status_code=400)
            return JSONResponse(content, status_code=response.status_code)
        # Handle GET requests
        response = await call_next(request)
        if request.method == "GET" and user:
            body = [chunk async for chunk in response.body_iterator]
            content = json.loads(b"".join(body).decode())
            if "download" in request.url.path:
                content, code = self.generate_presigned_url(content, request.url.path)
                return JSONResponse(content, status_code=code)
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
        return response
