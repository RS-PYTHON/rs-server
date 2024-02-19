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

    async def dispatch(self, request, call_next) -> None:
        """Redirect the user catalog specific endpoint and adapt the response content."""
        request.scope["path"], user = remove_user_prefix(request.url.path)
        response = await call_next(request)

        if request.method == "GET":
            body = [chunk async for chunk in response.body_iterator]
            content = json.loads(b"".join(body).decode())
            if request.scope["path"] == "/collections":
                content["collections"] = filter_collections(content["collections"], user)
                content = self.remove_user_from_objects(content, user, "collections")
                content = self.adapt_links(content, user)
            elif "items" not in request.scope["path"]:
                content = remove_user_from_collection(content, user)
                content = self.adapt_collection_links(content, user)
            else:
                content = self.remove_user_from_objects(content, user, "features")
            return JSONResponse(content, status_code=response.status_code)
        return response
