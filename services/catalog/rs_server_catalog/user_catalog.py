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
import pathlib
from urllib.parse import urlparse

from rs_server_catalog.user_handler import (
    add_user_prefix,
    filter_collections,
    remove_user_from_collection,
    remove_user_from_feature,
    remove_user_prefix,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


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
        if object_name == "collections":
            for i in range(nb_objects):
                objects[i] = remove_user_from_collection(objects[i], user)
        else:
            for i in range(nb_objects):
                objects[i] = remove_user_from_feature(objects[i], user)
        return content

    def adapt_collection_links(self, collection: dict, user: str) -> dict:
        """adapt all the links from a collection so the user can use them correctly

        Args:
            collection (dict): The collection
            user (str): The user id

        Returns:
            dict: The collection passed in parameter with adapted links
        """
        links = collection["links"]
        for j, link in enumerate(links):
            link_parser = urlparse(link["href"])
            new_path = add_user_prefix(link_parser.path, user, collection["id"])
            links[j]["href"] = link_parser._replace(path=new_path).geturl()
        return collection

    def adapt_links(self, content: dict, user: str) -> dict:
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
            new_path = add_user_prefix(link_parser.path, user, "")
            links[i]["href"] = link_parser._replace(path=new_path).geturl()
        for i in range(len(content["collections"])):
            content["collections"][i] = self.adapt_collection_links(content["collections"][i], user)
        return content

    @staticmethod
    def update_stac_item_publication(content: dict, user: str) -> dict:
        """Update json body of feature push to catalog"""
        # 1 - update assets href
        for asset in content["assets"]:
            filename = pathlib.Path(content["assets"][asset]["href"])
            for suffix in filename.suffixes:
                fid = str(filename).replace(suffix, "")
            new_href = (
                f'https://rs-server/catalog/{user}/collections/{content["collection"]}/items/{fid}/download/{asset}'
            )
            content["assets"][asset].update({"href": new_href})
            # 2 - update alternate href to define catalog s3 bucket
            s3_key = f"s3://catalog-bucket/{filename.name}"
            new_s3_href = {"s3": {"href": s3_key}}
            content["assets"][asset].update({"alternate": new_s3_href})

        # 3 - include new stac extension if not present

        new_stac_extension = "https://stac-extensions.github.io/alternate-assets/v1.1.0/schema.json"
        if new_stac_extension not in content["stac_extensions"]:
            content["stac_extensions"].append(new_stac_extension)
        # 4 tdb, bucket movement
        # from rs_server_common.s3_storage_handler import s3_storage_handler

        # 5 - add owner data
        content["owner"] = user
        content.update({"collection": f"{user}_{content['collection']}"})
        return content

    async def dispatch(self, request, call_next):
        """Redirect the user catalog specific endpoint and adapt the response content."""
        request.scope["path"], user = remove_user_prefix(request.url.path)
        if request.method == "POST" and user:
            # capture request from frontend and update the content
            # then forward it to pgstac
            if "items" in request.scope["path"]:
                content = await request.body()
                content = UserCatalogMiddleware.update_stac_item_publication(json.loads(content), user)
                # update request body (better find the function that updates the body maybe?)
                request._body = json.dumps(content).encode("utf-8")  # pylint: disable=protected-access
                try:
                    response = await call_next(request)
                except Exception as e:  # pylint: disable=broad-except
                    return JSONResponse(f"Bad request, {e}", status_code=400)
                return JSONResponse(content, status_code=response.status_code)
            # collection creation was here
            response = await call_next(request)
            # can this be moved up?
            body = [chunk async for chunk in response.body_iterator]
            content = json.loads(b"".join(body).decode())
            return JSONResponse(content, status_code=response.status_code)

        response = await call_next(request)
        if request.method == "GET" and user:
            body = [chunk async for chunk in response.body_iterator]
            content = json.loads(b"".join(body).decode())
            if request.scope["path"] == "/":
                return JSONResponse(content, status_code=response.status_code)
            if request.scope["path"] == "/collections":
                content["collections"] = filter_collections(content["collections"], user)
                content = self.remove_user_from_objects(content, user, "collections")
                content = self.adapt_links(content, user)
            elif "/collection" in request.scope["path"] and "items" not in request.scope["path"]:
                content = remove_user_from_collection(content, user)
                content = self.adapt_collection_links(content, user)
            elif "items" in request.scope["path"]:
                content = self.remove_user_from_objects(content, user, "features")
            return JSONResponse(content, status_code=response.status_code)
        return response
