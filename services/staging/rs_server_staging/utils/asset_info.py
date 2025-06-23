# Copyright 2025 CS Group
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

"""Representation of an asset for staging process"""

from dataclasses import dataclass


@dataclass
class AssetInfo:  # pylint: disable=too-many-instance-attributes
    """
    Dataclass with essential information for an asset to be staged.

    Args:
        product_url (str): Link to the item to stage
        s3_file (str): Path for the object in the S3 storage
        s3_bucket (str): Name of the bucket where the asset will be staged
        origin_service (str): Service used for staging (usually http or s3)
            When service is s3, access_key and secret_key are needed
        external_s3_access_key (str): Access key for staging from an external S3
        external_s3_secret_key (str): Secret key for staging from an external S3
    """

    product_url: str
    s3_file: str
    s3_bucket: str
    origin_service: str = "http"
    external_s3_endpoint_url: str = ""
    external_s3_access_key: str = ""
    external_s3_secret_key: str = ""
    trusted_domains: list[str] | None = None


class IncompleteAssetError(Exception):
    """Exception thrown when an asset is incomplete."""


class IncompleteFeatureError(Exception):
    """Exception thrown when a feature is incomplete."""
