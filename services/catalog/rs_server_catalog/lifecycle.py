import os

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

        cursor.execute(query, ("toto_S1_L1",))

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


def delete_assets_from_s3(expired_items):
    """Delete all assets linked to expired items."""
    for field in expired_items:
        if "assets" in field:
            for asset in field["assets"]:
                delete_asset_from_s3(asset)
            break


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
