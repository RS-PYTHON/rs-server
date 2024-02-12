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
from starlette.types import Send, Receive, Scope, ASGIApp

from rs_server_catalog.user_handler import remove_user_prefix


class UserCatalogMiddleware:
    """The user catalog middleware."""

    def __init__(self, app: ASGIApp) -> None:
        """Create a user catalog middleware.

        Args:
            app: the app
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Applies the middleware to a asgi event.

        Args:
            scope: the scope
            receive: callback to get/set the request
            send: callback to get/set the response

        Returns:
            Nothing
        """
        # This middleware is only for http request
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Redirect the user catalog specific endpoint
        # to the common stac api endpoint.
        scope["path"] = remove_user_prefix(URL(scope=scope).path)

        # Update the body response
        async def change_the_response(message):
            if message["type"] != "http.response.body":
                return await send(message)

            content = json.loads(message["body"])

            collections = content["collections"]
            links = content["links"]
            ...

            return await send(message)

        await self.app(scope, receive, change_the_response)