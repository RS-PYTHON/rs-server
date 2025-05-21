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


class AssetInfo:
    """Dataclass with essential information for an asset to be staged.

    Args:
        href (str): Link to the item to stage
        s3_obj_path (str): Path for the object in the S3 storage
        s3_bucket (str): Name of the bucket where the asset will be staged
    """

    def __init__(self, href: str, s3_obj_path: str, s3_bucket: str):
        self.href = href
        self.s3_obj_path = s3_obj_path
        self.s3_bucket = s3_bucket

    def get_href(self) -> str:
        """Returns asset's href.

        Returns:
            str: Link to the item (href)
        """
        return self.href

    def get_s3_object_path(self) -> str:
        """Returns asset's S3 object path.

        Returns:
            str: S3 object path for this item
        """
        return self.s3_obj_path

    def get_s3_bucket(self) -> str:
        """Returns asset's S3 bucket name.

        Returns:
            str: S3 bucket name for this item
        """
        return self.s3_bucket
