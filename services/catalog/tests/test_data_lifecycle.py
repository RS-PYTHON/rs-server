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
import json
import os
from datetime import datetime
from urllib.parse import urlparse

import requests
from moto.server import ThreadedMotoServer
from rs_server_catalog.timestamps_extension import ISO_8601_FORMAT
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler

from tests.helpers import (
    a_collection,
    add_collection,
    clear_aws_credentials,
    export_aws_credentials,
)

user = "toto"
temp_bucket = "temp-bucket"
temp_bucket_path = f"s3://{temp_bucket}/"
catalog_bucket = "rspython-ops-catalog-all-production"  # Default bucket from the config file
old_date: str = datetime(2000, 1, 1).strftime(ISO_8601_FORMAT)


def get_item(client, collection_id: str, item_id: str) -> dict:
    """Get item from the stac catalog"""
    response = client.get(f"/catalog/collections/{user}:{collection_id}/items/{item_id}")
    response.raise_for_status()
    return response.json()


def check_assets(s3_handler, item: dict, exist: bool):
    """Check that all asset files exist (or not) in the s3 bucket"""
    files = [asset["alternate"]["s3"]["href"] for asset in item.get("assets", {}).values()]
    for s3_file in files:
        parsed = urlparse(s3_file)
        bucket_name = parsed.netloc
        bucket_key = parsed.path.strip("/")
        objects = s3_handler.list_s3_files_obj(bucket_name, bucket_key)
        if exist:
            assert objects, f"{s3_file!r} is missing"
        else:
            assert not objects, f"{s3_file!r} should have been removed"


async def test_data_lifecycle(client, a_correct_feature):
    """Test the data lifecycle"""

    # async with lifecycle.fake_request.app.state.get_connection(lifecycle.fake_request, "r") as conn:
    #     bp = 0

    # test_item = await lifecycle.client_search.get_item(
    #     item_id="item_id",
    #     collection_id="col_name",
    #     request=lifecycle.request,
    # )
    bp = 0

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

        # Order item by collection and id
        expired_items: dict[tuple[str, str], dict] = {}
        unexpired_items: dict[tuple[str, str], dict] = {}

        # Create n test collections
        col_names = [f"collection_lifecycle_{i}" for i in range(2)]
        for col_name in col_names:
            add_collection(client, a_collection(user, col_name))

            # Post n items. Start from the default feature, modify fields.
            item_ids = [f"item_{i}" for i in range(3)]
            for item_id in item_ids:
                local_item = copy.deepcopy(a_correct_feature)
                local_item["id"] = item_id
                local_item["collection"] = col_name
                local_item["assets"] = {
                    f"{col_name}.{item_id}.asset_{i}": {
                        "href": f"{temp_bucket_path}{col_name}.{item_id}.asset_{i}",
                        "roles": ["data"],
                    }
                    for i in range(3)
                }

                # Upload dummy assets to the temp bucket.
                # Then they will be copied to the final bucket by rs-server.
                for key in local_item["assets"].values():
                    s3_handler.s3_client.put_object(
                        Bucket=temp_bucket,
                        Key=key["href"].removeprefix(temp_bucket_path),
                        Body="testing\n",
                    )
                assert s3_handler.list_s3_files_obj(temp_bucket, "")

                # Mark only the first n items of the first collection to be expired
                stac_item = {}
                expired = False
                if len(expired_items) < 2:
                    local_item["properties"]["expires"] = old_date
                    expired_items[(col_name, item_id)] = stac_item
                    expired = True
                else:
                    unexpired_items[(col_name, item_id)] = stac_item

                # POST stac feature
                client.post(f"/catalog/collections/{user}:{col_name}/items", json=local_item).raise_for_status()

                # Before triggering the data lifecycle, get the item back from the stac catalog
                # and save its contents
                stac_item.update(get_item(client, col_name, item_id))

                # Check that the expire date is as requested
                if expired:
                    assert stac_item["properties"]["expires"] == old_date

                # For now the item should have no unpublised field and the files should exist in the bucket
                assert "unpublished" not in stac_item["properties"]
                check_assets(s3_handler, stac_item, exist=True)

        # Trigger the data lifecyle
        client.get("/data/lifecycle").raise_for_status()

        # For each expired item
        for (col_name, item_id), old_item in expired_items.items():

            # Get the new item values from the stac catalog
            new_item = get_item(client, col_name, item_id)

            # The new updated date should be more recent
            old_updated = datetime.fromisoformat(old_item["properties"].pop("updated"))
            new_updated = datetime.fromisoformat(new_item["properties"].pop("updated"))
            assert new_updated > old_updated

            # The unpublished date should be set in the new item
            assert new_item["properties"].pop("unpublished")

            # There should be several assets in the old item, and none in the cleaned item
            assert old_item.pop("assets")
            assert not new_item.pop("assets")

            # Apart from the above fields, all others should have stayed the same
            assert (
                old_item == new_item
            ), f"Different values for item:\n{json.dumps(old_item, indent=2)}\nVS\n{json.dumps(new_item, indent=2)}"

        # On the other hand, the items that are not expired were not changed by the data lifecycle
        for (col_name, item_id), old_item in unexpired_items.items():
            new_item = get_item(client, col_name, item_id)
            assert (
                old_item == new_item
            ), f"Different values for item:\n{json.dumps(old_item, indent=2)}\nVS\n{json.dumps(new_item, indent=2)}"

    finally:
        server.stop()
        clear_aws_credentials()
        os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"
