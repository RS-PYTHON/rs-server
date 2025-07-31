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

import asyncio
import copy
import json
from datetime import datetime
from urllib.parse import urlparse

import pytest
from rs_server_catalog.data_lifecycle import DataLifecycle
from rs_server_catalog.timestamps_extension import ISO_8601_FORMAT

from tests.helpers import (
    TEMP_BUCKET,
    a_collection,
    add_collection,
)

USER = "lifecycleuser"
TEMP_BUCKET_PATH = f"s3://{TEMP_BUCKET}/"
OLD_DATE: str = datetime(2000, 1, 1).strftime(ISO_8601_FORMAT)


def get_item(client, collection_id: str, item_id: str) -> dict:
    """Get item from the stac catalog"""
    response = client.get(f"/catalog/collections/{USER}:{collection_id}/items/{item_id}")
    response.raise_for_status()
    return response.json()


def check_assets(s3_handler, item: dict, exist: bool):
    """Check that all asset files exist (or not) in the s3 bucket"""
    files = [asset["href"] for asset in item.get("assets", {}).values()]
    for s3_file in files:
        parsed = urlparse(s3_file)
        bucket_name = parsed.netloc
        bucket_key = parsed.path.strip("/")
        objects = s3_handler.list_s3_files_obj(bucket_name, bucket_key)
        if exist:
            assert objects, f"{s3_file!r} is missing"
        else:
            assert not objects, f"{s3_file!r} should have been removed"


async def test_data_lifecycle_once(client, init_buckets, a_correct_feature):
    """Test the data lifecycle when it is run once"""
    s3_handler = init_buckets.s3_handler
    try:
        # Order item by collection and id
        expired_items: dict[tuple[str, str], dict] = {}
        unexpired_items: dict[tuple[str, str], dict] = {}

        # Create n test collections
        col_names = [f"collection_lifecycle_{i}" for i in range(2)]
        for col_name in col_names:
            add_collection(client, a_collection(USER, col_name))

            # Post n items. Start from the default feature, modify fields.
            item_ids = [f"item_{i}" for i in range(3)]
            for item_id in item_ids:
                local_item = copy.deepcopy(a_correct_feature)
                local_item["id"] = item_id
                local_item["collection"] = col_name
                local_item["assets"] = {
                    f"{col_name}.{item_id}.asset_{i}": {
                        "href": f"{TEMP_BUCKET_PATH}{col_name}.{item_id}.asset_{i}",
                        "roles": ["data"],
                    }
                    for i in range(3)
                }

                # Upload dummy assets to the temp bucket.
                # Then they will be copied to the final bucket by rs-server.
                for key in local_item["assets"].values():
                    s3_handler.s3_client.put_object(
                        Bucket=TEMP_BUCKET,
                        Key=key["href"].removeprefix(TEMP_BUCKET_PATH),
                        Body="testing\n",
                    )
                assert s3_handler.list_s3_files_obj(TEMP_BUCKET, "")

                # Mark only the first n items of the first collection to be expired
                stac_item: dict = {}
                expired = False
                if len(expired_items) < 2:
                    local_item["properties"]["expires"] = OLD_DATE
                    expired_items[(col_name, item_id)] = stac_item
                    expired = True
                else:
                    unexpired_items[(col_name, item_id)] = stac_item

                # POST stac feature
                client.post(f"/catalog/collections/{USER}:{col_name}/items", json=local_item).raise_for_status()

                # Before triggering the data lifecycle, get the item back from the stac catalog
                # and save its contents
                stac_item.update(get_item(client, col_name, item_id))

                # Check that the expire date is as requested
                if expired:
                    assert stac_item["properties"]["expires"] == OLD_DATE

                # For now the item should have no unpublised field and the files should exist in the bucket
                assert "unpublished" not in stac_item["properties"]
                check_assets(s3_handler, stac_item, exist=True)

        # Trigger the data lifecyle
        client.get("/data/lifecycle").raise_for_status()

        # For each expired item
        for (col_name, item_id), old_item in expired_items.items():

            # The assets should have been deleted from the bucket
            check_assets(s3_handler, old_item, exist=False)

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
            check_assets(s3_handler, old_item, exist=True)
            new_item = get_item(client, col_name, item_id)
            assert (
                old_item == new_item
            ), f"Different values for item:\n{json.dumps(old_item, indent=2)}\nVS\n{json.dumps(new_item, indent=2)}"

    finally:
        # Clean catalog
        for col_name in col_names:
            client.delete(f"/catalog/collections/{USER}:{col_name}").raise_for_status()


@pytest.mark.parametrize("test_error", [False, True], ids=["nominal", "error"])
async def test_data_lifecycle_loop(mocker, monkeypatch, test_error: bool):
    """Test the data lifecycle automatic loop"""

    # Mock the period in seconds between two tasks
    monkeypatch.setenv("RSPY_DATA_LIFECYCLE_PERIOD", "0.1")

    # Dummy instance
    lifecycle = DataLifecycle(None, None)
    error_message = "mocked error message !"
    mock_periodic_once = mocker.patch.object(
        lifecycle,
        "periodic_once",
        side_effect=RuntimeError(error_message) if test_error else None,
    )

    # Errors are logged, not raised
    if test_error:
        mock_logger_error = mocker.patch.object(lifecycle.logger, "error")

    # Trigger the periodic task
    lifecycle.run()

    # Wait n seconds, cancel it and wait a little more
    await asyncio.sleep(0.5)
    await lifecycle.cancel()
    await asyncio.sleep(0.1)

    # The task should have been called multiple times
    old_call_count = mock_periodic_once.call_count
    assert old_call_count >= 4

    # An error should be logged for every call
    if test_error:
        assert mock_logger_error.call_count == old_call_count
        for error_arg in mock_logger_error.call_args_list:
            assert f"RuntimeError: {error_message}" in str(error_arg)

    # If we wait more, the task should not be called anymore after being cancelled
    await asyncio.sleep(0.5)
    assert old_call_count == mock_periodic_once.call_count
