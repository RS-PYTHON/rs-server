# Copyright 2024 CS Group
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

#  _     _  __                      _
# | |   (_)/ _| ___  ___ _   _  ___| | ___
# | |   | | |_ / _ \/ __| | | |/ __| |/ _ \
# | |___| |  _|  __/ (__| |_| | (__| |  __/
# |_____|_|_|  \___|\___|\__, |\___|_|\___|
#                        |___/

"""Control the data lifecycle with automatic cleanup of expired data"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
import psycopg2
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler

BUCKET_NAME = "rs-cluster-catalog"


def check_expired_items(database_url):
    """Select each item with a field 'expires' that is expired."""

    # Connect to the database
    try:
        connection = psycopg2.connect(database_url)
        cursor = connection.cursor()

        # Define the SQL query to retrieve the collection with id 'toto_S1_L1'
        query = """
                SELECT *
                FROM items
                WHERE (content->'properties'->>'expires')::timestamptz < now()
                """

        cursor.execute(query)

        # Fetch all results
        expired_items = cursor.fetchall()

        return expired_items

    except Exception as e:
        print(f"Error checking expired items: {e}")
    finally:
        # Close the connection
        if connection:
            cursor.close()
            connection.close()


def manage_expired_items(expired_items):
    """Delete all assets linked to expired items."""
    for expired_item in expired_items:
        now = datetime.now(ZoneInfo("UTC"))
        if len(expired_item) == 6:  # In this part we try to get the assets to be deleted.
            content = expired_item[5]
            if "assets" in content:
                assets = content["assets"]
                for asset in assets:
                    delete_asset_from_s3(assets[asset])
            properties = content["properties"]
            properties["unpublished"] = now
            properties["updated"] = now


def delete_asset_from_s3(asset):
    """Delete one asset in a s3 bucket."""
    try:
        s3_handler = S3StorageHandler(
            os.environ["S3_ACCESSKEY"],
            os.environ["S3_SECRETKEY"],
            os.environ["S3_ENDPOINT"],
            os.environ["S3_REGION"],
        )

        prefix = f"s3://{BUCKET_NAME}/"
        prefix_size = len(prefix)
        s3_object = asset["href"][prefix_size:]
        s3_handler.delete_file_from_s3(bucket=BUCKET_NAME, s3_obj=s3_object)
    except KeyError as e:
        raise RuntimeError("Could not find s3 credentials") from e
    except Exception as e:
        raise RuntimeError("General exception when trying to access bucket") from e


def update_expired_item(item, database_url):
    """Once the item is processed, update the content in the database."""
    # Connect to the database
    try:
        connection = psycopg2.connect(database_url)
        cursor = connection.cursor()

        # Define the SQL query to retrieve the collection with id 'toto_S1_L1'
        query = """
                UPDATE stac_items
                SET content = jsonb_set(content, '{properties, datetime}', '"2024-01-01T00:00:00Z"', false)
                WHERE id = 'your-item-id'
                """

        query = (
            """
            UPDATE stac_items
            SET content = content
                || jsonb_build_object('assets', '{}'::jsonb)
                || jsonb_build_object('properties', content->'properties' || jsonb_build_object(
                    'updated', to_jsonb(NOW()),
                    'unpublished', to_jsonb(NOW())
                ))
            """
            + f" WHERE id = '{item[id]}'"
        )

        cursor.execute(query)

        # Fetch all results
        expired_items = cursor.fetchall()

        return expired_items

    except Exception as e:
        print(f"Error updating expired item: {e}")
    finally:
        # Close the connection
        if connection:
            cursor.close()
            connection.close()


def run():
    """The data life cycle run."""
    day_in_second = 3600 * 24
    frequency = int(os.environ.get("LIFE_CYCLE_FREQUENCY", "1"))
    data_base_url = os.environ["DATA_BASE_URL"]
    while True:
        expired_items = check_expired_items(data_base_url)
        manage_expired_items(expired_items)
        time.sleep(day_in_second / frequency)
