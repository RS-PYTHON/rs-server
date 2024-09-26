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

import psycopg2
from prefect import flow, task
from prefect.docker import DockerImage
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler

# import time


BUCKET_NAME = "rs-cluster-catalog"


@task
def check_expired_items(connection: psycopg2.extensions.connection) -> list:
    """Select each item with an 'expires' field that has already expired.

    Args:
        connection (psycopg2.extensions.connection): The connection to the database.
    Returns:
        list: The list of expired items."""
    expired_items = []
    try:
        cursor = connection.cursor()
        # Define the SQL query to retrieve the expired items.
        query = """
                SELECT *
                FROM items
                WHERE (content->'properties'->>'expires')::timestamptz < now()
                """

        cursor.execute(query)

        # Fetch all results
        expired_items = cursor.fetchall()
    except psycopg2.DatabaseError as e:
        print(f"Database error: {e}")
    except psycopg2.OperationalError as e:
        print(f"Operationnal error (connection issue): {e}")
    except psycopg2.ProgrammingError as e:
        print(f"SQL query error: {e}")
    except psycopg2.DatabaseError as e:
        print(f"Data error: {e}")
    except psycopg2.IntegrityError as e:
        print(f"Integrity constraint error: {e}")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"An unexpected error occurred: {e}")
    finally:
        # Close the connection
        if connection:
            cursor.close()
    return expired_items


@task
def manage_expired_items(expired_items: list, connection: psycopg2.extensions.connection) -> None:
    """Delete all assets linked to expired items.

    Args:
        expired_items (list): The list of expired items.
        connection (psycopg2.extensions.connection): The connection to the database."""
    for expired_item in expired_items:
        if len(expired_item) == 6:  # In this part we try to get the assets to be deleted.
            content = expired_item[5]
            if "assets" in content:
                assets = content["assets"]
                for asset in assets:
                    delete_asset_from_s3(assets[asset])
        update_expired_item(expired_item, connection)


@task
def delete_asset_from_s3(asset: dict) -> None:
    """Delete one asset in an s3 bucket.

    Args:
        asset (dict): The asset to be deleted.
    Raises:
        KeyError: If there are errors while connecting to the s3 bucket."""
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


@task
def update_expired_item(item: dict, connection: psycopg2.extensions.connection) -> None:
    """Once the item is processed, update the content in the database.

    Args:
        item (dict): The item to be updated.
        connection (psycopg2.extensions.connection): The connection to the database."""
    # Connect to the database
    try:
        cursor = connection.cursor()

        # Define the SQL query to retrieve the collection with a specific id.
        query = (
            """
            UPDATE items
            SET content = content
                || jsonb_build_object('assets', '{}'::jsonb)
                || jsonb_build_object('properties', content->'properties' || jsonb_build_object(
                    'updated', to_jsonb(NOW()),
                    'unpublished', to_jsonb(NOW())
                ))
            """
            + f"WHERE id = '{item[0]}'"
        )

        cursor.execute(query)

        # Commit the changes
        connection.commit()
    except psycopg2.DatabaseError as e:
        print(f"Database error: {e}")
    except psycopg2.OperationalError as e:
        print(f"Operationnal error (connection issue): {e}")
    except psycopg2.ProgrammingError as e:
        print(f"SQL query error: {e}")
    except psycopg2.DatabaseError as e:
        print(f"Data error: {e}")
    except psycopg2.IntegrityError as e:
        print(f"Integrity constraint error: {e}")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"An unexpected error occurred: {e}")
    finally:
        # Close the connection
        if connection:
            cursor.close()


@flow(log_prints=True)
def run():
    """The data life cycle run."""
    print("Loads variables.")
    db_user = os.environ["POSTGRES_USER"]
    db_password = os.environ["POSTGRES_PASSWORD"]
    db_port = os.environ["POSTGRES_PORT"]
    db_name = os.environ["POSTGRES_DBNAME"]
    db_host = os.environ["POSTGRES_HOST"]

    print("Connect to the database 💾.")
    try:
        connection = psycopg2.connect(
            user=db_user,
            password=db_password,
            port=db_port,
            dbname=db_name,
            host=db_host,
        )

        print("Retrieve expired items... ⏳")
        expired_items = check_expired_items(connection)
        print(f"Found {len(expired_items)} expired items 📚!")

        if expired_items:
            print("Managing expired items... ⏳")
            manage_expired_items(expired_items, connection)
            print("all items have been processed ! ✅")

    except psycopg2.DatabaseError as e:
        print(f"Database error: {e}")
    except psycopg2.OperationalError as e:
        print(f"Operationnal error (connection issue): {e}")
    except psycopg2.ProgrammingError as e:
        print(f"SQL query error: {e}")
    except psycopg2.DatabaseError as e:
        print(f"Data error: {e}")
    except psycopg2.IntegrityError as e:
        print(f"Integrity constraint error: {e}")
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"An unexpected error occurred: {e}")
    finally:
        # Close the connection
        if connection:
            connection.close()


if __name__ == "__main__":
    run.deploy(
        name="data_life_cycle_deployment",
        work_pool_name="my-docker-pool",
        image=DockerImage(name="data_life_cycle_image", tag="latest", dockerfile="Dockerfile"),
        push=False,
    )
