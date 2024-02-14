"""An ASGI middleware to handle the user multi catalog.

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

from starlette.datastructures import URL
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from urllib.parse import urlparse

from rs_server_catalog.user_handler import (
    remove_user_prefix,
    remove_user_from_collection,
    filter_collections,
    add_user_prefix,
    remove_user_from_feature,
)


class UserCatalogMiddleware(BaseHTTPMiddleware):
    """The user catalog middleware."""

    def remove_user_from_collections(self, content: dict, user: str):
        collections = content["collections"]
        nb_collections = len(collections)
        for i in range(nb_collections):
            collections[i] = remove_user_from_collection(collections[i], user)
        return content

    def remove_user_from_features(self, content: dict, user: str):
        features = content["features"]
        nb_features = len(features)
        for i in range(nb_features):
            features[i] = remove_user_from_feature(features[i], user)
        return content

    def adapt_collection_links(self, collection: dict, user: str):
        links = collection["links"]
        for j in range(len(links)):
            link_parser = urlparse(links[j]["href"])
            new_path = add_user_prefix(link_parser.path, user, collection["id"])
            links[j]["href"] = link_parser._replace(path=new_path).geturl()
        return collection

    def adapt_links(self, content: dict, user: str):
        links = content["links"]
        for i in range(len(links)):
            link_parser = urlparse(links[i]["href"])
            new_path = add_user_prefix(link_parser.path, user, "")
            links[i]["href"] = link_parser._replace(path=new_path).geturl()
        for i in range(len(content["collections"])):
            content["collections"][i] = self.adapt_collection_links(content["collections"][i], user)
        return content

    async def dispatch(self, request, call_next) -> None:

        # Redirect the user catalog specific endpoint
        # to the common stac api endpoint.
        request.scope["path"], user = remove_user_prefix(request.url.path)
        response = await call_next(request)

        if request.method == "GET":
            body = [chunk async for chunk in response.body_iterator]
            content = json.loads(b"".join(body).decode())
            if request.scope["path"] == "/collections":
                content["collections"] = filter_collections(content["collections"], user)
                content = self.remove_user_from_collections(content, user)
                content = self.adapt_links(content, user)
            elif "items" not in request.scope["path"]:
                content = remove_user_from_collection(content, user)
                content = self.adapt_collection_links(content, user)
            else:
                content = self.remove_user_from_features(content, user)
            return JSONResponse(content, status_code=response.status_code)
        return response
