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

"""Test the data lifecycle (cleaning of old items)"""

import copy
import os

import requests
from moto.server import ThreadedMotoServer
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler

from tests.helpers import (
    a_collection,
    add_collection,
    clear_aws_credentials,
    export_aws_credentials,
)

user = "toto"
temp_bucket = "temp-bucket"
catalog_bucket = "rspython-ops-catalog-all-production"  # Default bucket from the config file


async def test_data_lifecycle(client, a_correct_feature):
    """Test the data lifecycle"""

    # Create moto server and temp / catalog bucket
    moto_endpoint = "http://localhost:8077"
    export_aws_credentials()
    secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
    # Enable bucket transfer
    os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"
    server = ThreadedMotoServer(port=8077)
    server.start()
    try:
        requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )

        s3_handler.s3_client.create_bucket(Bucket=temp_bucket)
        s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)
        assert not s3_handler.list_s3_files_obj(temp_bucket, "")
        assert not s3_handler.list_s3_files_obj(catalog_bucket, "")

        # Create n test collections
        col_names = [f"collection_lifecycle_{i}" for i in range(2)]
        for col_name in col_names:
            add_collection(client, a_collection(user, col_name))

            # Post n items. Start from the default feature, modify fields.
            item_names = [f"item_{i}" for i in range(3)]
            for item_name in item_names:
                feature = copy.deepcopy(a_correct_feature)
                feature["id"] = item_name
                feature["collection"] = col_name
                feature["assets"] = {
                    f"{item_name}.asset_{i}": {
                        "href": f"s3://temp-bucket/{item_name}.asset_{i}",
                        "roles": ["data"],
                    }
                    for i in range(3)
                }

                # Upload dummy assets to the temp bucket.
                # Then they will be copied to the final bucket by rs-server.
                for key in feature["assets"].values():
                    s3_handler.s3_client.put_object(Bucket=temp_bucket, Key=key["href"], Body="testing\n")
                assert s3_handler.list_s3_files_obj(temp_bucket, "")

                # POST stac feature
                added_feature = client.post(f"/catalog/collections/{user}:{col_name}/items", json=feature)
                added_feature.raise_for_status()
                bp = 0

    finally:
        server.stop()
        clear_aws_credentials()
        os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"
