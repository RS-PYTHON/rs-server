# Copyright 2023-2025 Airbus, CS Group
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
"""Module grouping functions dedicated to the manipulation of STAC data"""

import os
from urllib.parse import urlparse

from fastapi import HTTPException
from rs_server_catalog.data_management.user_handler import add_user_prefix
from rs_server_catalog.utils import ALTERNATE_STRING, is_s3_path
from rs_server_common import settings as common_settings
from rs_server_common.authentication import oauth2
from rs_server_common.utils.logging import Logging
from starlette.status import HTTP_400_BAD_REQUEST

logger = Logging.default(__name__)


class StacManager:
    """Class grouping functions dedicated to the manipulation of STAC data"""

    @staticmethod
    async def add_authentication_extension(content: dict) -> None:
        """Add the stac authentication extension, see: https://github.com/stac-extensions/authentication

        Args:
            content (dict): STAC description of the object to which add the authentication extension
        """

        # Only on cluster mode
        if not common_settings.CLUSTER_MODE:
            return

        # Read environment variables
        oidc_endpoint = os.environ["OIDC_ENDPOINT"]
        oidc_realm = os.environ["OIDC_REALM"]
        oidc_metadata_url = f"{oidc_endpoint}/realms/{oidc_realm}/.well-known/openid-configuration"

        # Add the STAC extension at the root
        extensions = content.setdefault("stac_extensions", [])
        url = "https://stac-extensions.github.io/authentication/v1.1.0/schema.json"
        if url not in extensions:
            extensions.append(url)

        # Add the authentication schemes under the root or "properties" (for the items)
        parent = content
        if content.get("type") == "Feature":
            parent = content.setdefault("properties", {})
        oidc = await oauth2.KEYCLOAK.load_server_metadata()
        parent.setdefault("auth:schemes", {}).update(
            {
                "apikey": {
                    "type": "apiKey",
                    "description": f"API key generated using {os.environ['RSPY_UAC_HOMEPAGE']}"  # link to /docs
                    # add anchor to the "new api key" endpoint
                    "#/Manage%20API%20keys/get_new_api_key_auth_api_key_new_get",
                    "name": "x-api-key",
                    "in": "header",
                },
                "openid": {
                    "type": "openIdConnect",
                    "description": "OpenID Connect",
                    "openIdConnectUrl": oidc_metadata_url,
                },
                "oauth2": {
                    "type": "oauth2",
                    "description": "OAuth2+PKCE Authorization Code Flow",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": oidc["authorization_endpoint"],
                            "tokenUrl": oidc["token_endpoint"],
                            "scopes": {},
                        },
                    },
                },
                "s3": {
                    "type": "s3",
                    "description": "S3",
                },
            },
        )

        # Add the authentication reference to each link and asset
        for link in content.get("links", []):
            link["auth:refs"] = ["apikey", "openid", "oauth2"]
        for asset in list(content.get("assets", {}).values()):
            asset["auth:refs"] = ["s3"]
            if ALTERNATE_STRING in asset:
                asset[ALTERNATE_STRING].update({"auth:refs": ["apikey", "openid", "oauth2"]})
        # Add the extension to the response root and to nested collections, items, ...
        # Do recursive calls to all nested fields, if defined
        for nested_field in ["collections", "features"]:
            for nested_content in content.get(nested_field, []):
                await StacManager.add_authentication_extension(nested_content)

    @staticmethod
    def update_stac_catalog_metadata(metadata: dict) -> None:
        """Update the metadata fields from a catalog

        Args:
            metadata (dict): The metadata that has to be updated. The fields id, title,
                            description and stac_version are to be updated, by using the env vars which have
                            to be set before starting the app/pod. The existing values are used if
                            the env vars are not found
        """
        if metadata.get("type") == "Catalog":
            for key in ["id", "title", "description", "stac_version"]:
                if key in metadata:
                    metadata[key] = os.environ.get(f"CATALOG_METADATA_{key.upper()}", metadata[key])

    @staticmethod
    def update_links_for_all_collections(collections: list[dict]) -> list[dict]:
        """Update the links for the endpoint /catalog/collections.

        Args:
            collections (list[dict]): all the collections to be updated.

        Returns:
            list[dict]: all the collections after the links updated.
        """
        for collection in collections:
            owner_id = collection["owner"]
            collection["id"] = collection["id"].removeprefix(f"{owner_id}_")
            for link in collection["links"]:
                link_parser = urlparse(link["href"])
                new_path = add_user_prefix(link_parser.path, owner_id, collection["id"])
                link["href"] = link_parser._replace(path=new_path).geturl()
        return collections

    @staticmethod
    def get_s3_filename_from_asset(asset: dict) -> tuple[str, bool]:
        """
        Retrieve the S3 key from the asset content.

        During the staging process, the content of the asset should be:
            "filename": {
                "href": "s3://temp_catalog/path/to/filename",
            }

        Once the asset is inserted in the catalog, the content typically looks like this:
            "filename": {
                "alternate": {
                    "https": {
                        "https://127.0.0.1:8083/catalog/collections/user:collection_name/items/filename/download/file",
                    }
                },
                "href": "s3://rs-dev-cluster-catalog/path/to/filename",
            }

        Args:
            asset (dict): The content of the asset.

        Returns:
            tuple[str, bool]: A tuple containing the full S3 path of the object and a boolean indicating
                            whether the S3 key was retrieved from the 'alternate' field.

        Raises:
            HTTPException: If the S3 key could not be loaded or is invalid.
        """
        # Attempt to retrieve the S3 key from the 'alternate.s3.href' or 'href' fields
        s3_filename = asset.get("href", "")
        alternate_field = bool(asset.get("alternate", None))

        # Validate that the S3 key was successfully retrieved and has the correct format
        if not is_s3_path(s3_filename):
            raise HTTPException(
                detail=f"Failed to load the S3 key from the asset content {asset}",
                status_code=HTTP_400_BAD_REQUEST,
            )

        return s3_filename, alternate_field
