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

#  _            _     _ _  __                      _
# | |_ ___  ___| |_  | (_)/ _| ___  ___ _   _  ___| | ___
# | __/ _ \/ __| __| | | | |_ / _ \/ __| | | |/ __| |/ _ \
# | ||  __/\__ \ |_  | | |  _|  __/ (__| |_| | (__| |  __/
#  \__\___||___/\__| |_|_|_|  \___|\___|\__, |\___|_|\___|
#                                       |___/

"""Tests for life cycle catalog."""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
import requests
from moto.server import ThreadedMotoServer
from rs_server_catalog.lifecycle import (
    check_expired_items,
    delete_asset_from_s3,
    manage_expired_items,
    run,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler

from tests.test_endpoints import clear_aws_credentials, export_aws_credentials


class TestCatalogLifeCycle:
    """This class contains integration tests for the life cycle management."""

    db_user = os.environ["POSTGRES_USER"]
    db_password = os.environ["POSTGRES_PASSWORD"]
    db_port = os.environ["POSTGRES_PORT"]
    db_name = os.environ["POSTGRES_DBNAME"]
    db_host = os.environ["POSTGRES_HOST"]
    past_date = datetime.now(ZoneInfo("UTC")) - timedelta(days=60)
    expired_date = past_date + timedelta(days=30)
    item = {
        "id": "expired_item",
        "stac_version": "1.0.0",
        "collection": "toto_S1_L1",
        "bbox": [-94.6334839, 37.0332547, -94.6005249, 37.0595608],
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-94.6334839, 37.0595608],
                    [-94.6334839, 37.0332547],
                    [-94.6005249, 37.0332547],
                    [-94.6005249, 37.0595608],
                    [-94.6334839, 37.0595608],
                ],
            ],
        },
        "properties": {
            "datetime": past_date.isoformat(),
            "gsd": 0.5971642834779395,
            "width": 2500,
            "height": 2500,
            "proj:epsg": 3857,
            "orientation": "nadir",
            "owner_id": "toto",
            "expires": expired_date.isoformat(),
        },
        "assets": {
            "may24C355000e4102500n.tif": {
                "href": "s3://catalog-bucket/toto_S1_L1/images/may24C355000e4102500n.tif",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "title": "NOAA STORM COG",
            },
        },
        "stac_extensions": [
            "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
            "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
        ],
    }

    def test_check_expired_items(self):
        """test the check expired items function."""
        # Connect to the PostgreSQL database
        connection = psycopg2.connect(
            user=self.db_user,
            password=self.db_password,
            port=self.db_port,
            dbname=self.db_name,
            host=self.db_host,
        )
        now = datetime.now(ZoneInfo("UTC"))

        try:

            # Create a cursor to execute the query
            cursor = connection.cursor()
            cursor.execute("""ALTER TABLE _items_1 DROP CONSTRAINT _items_1_dt""")

            cursor.execute(
                """
                INSERT INTO items (id, collection, geometry, datetime, end_datetime, content)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    self.item["id"],
                    self.item["collection"],
                    json.dumps(self.item["geometry"]),
                    self.past_date,
                    now,
                    json.dumps(
                        {
                            "bbox": self.item["bbox"],
                            "assets": self.item["assets"],
                            "properties": self.item["properties"],
                            "stac_extensions": self.item["stac_extensions"],
                        },
                    ),
                ),
            )

            # Commit the changes
            connection.commit()

            print("Item inserted successfully.")

            # Verify insertion
            verify_query = """
            SELECT * FROM items WHERE id = %s;
            """
            cursor.execute(verify_query, (self.item["id"],))
            inserted_item = cursor.fetchone()

            if inserted_item:
                print("Inserted item found:", inserted_item)
            else:
                print("No item found with the given ID.")

            expired_items = check_expired_items(connection)
            assert len(expired_items) == 1

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
            # Close the cursor and connection
            cursor.close()
            connection.close()

    def test_delete_assets_from_s3(self):
        """Test used to verify that the function is correctly deleting the assing from the s3 bucket."""
        # Create moto server and catalog-bucket
        moto_endpoint = "http://localhost:8077"
        catalog_bucket = "rs-cluster-catalog"
        export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        # Enable bucket transfer
        os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"
        server = ThreadedMotoServer(port=8077)
        server.start()
        try:
            requests.post(f"{moto_endpoint}/moto-api/reset", timeout=5)
            s3_handler = S3StorageHandler(
                secrets["accesskey"],
                secrets["secretkey"],
                secrets["s3endpoint"],
                secrets["region"],
            )

            s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)

            # Populate catalog-bucket with files.
            lst_with_files_to_be_copied = ["may24C355000e4102500n.tif"]
            for obj in lst_with_files_to_be_copied:
                s3_handler.s3_client.put_object(Bucket=catalog_bucket, Key=obj, Body="testing\n")

            bucket_files = s3_handler.list_s3_files_obj(bucket=catalog_bucket, prefix="")
            assert len(bucket_files) > 0

            asset_to_delete = {
                "href": "s3://catalog-bucket/toto_S1_L1/images/may24C355000e4102500n.tif",
                "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                "title": "NOAA STORM COG",
            }

            delete_asset_from_s3(asset_to_delete)

            # Check that the file is correctyl deleted.
            bucket_files = s3_handler.list_s3_files_obj(bucket=catalog_bucket, prefix="toto_S1_L1/images")
            assert not bucket_files
        except Exception as e:
            raise RuntimeError("error") from e
        finally:
            server.stop()
            clear_aws_credentials()
            os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"

    def test_one_run(self):  # pylint: disable=too-many-locals, too-many-statements
        """Test the entire process one time."""
        # Connect to the PostgreSQL database
        connection = psycopg2.connect(
            user=self.db_user,
            password=self.db_password,
            port=self.db_port,
            dbname=self.db_name,
            host=self.db_host,
        )
        now = datetime.now(ZoneInfo("UTC"))

        try:

            # Create a cursor to execute the query
            cursor = connection.cursor()
            cursor.execute("""ALTER TABLE _items_1 DROP CONSTRAINT _items_1_dt""")

            cursor.execute(
                """
                INSERT INTO items (id, collection, geometry, datetime, end_datetime, content)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,
                (
                    self.item["id"],
                    self.item["collection"],
                    json.dumps(self.item["geometry"]),
                    self.past_date,
                    now,
                    json.dumps(
                        {
                            "bbox": self.item["bbox"],
                            "assets": self.item["assets"],
                            "properties": self.item["properties"],
                            "stac_extensions": self.item["stac_extensions"],
                        },
                    ),
                ),
            )

            # Commit the changes
            connection.commit()
            # Create moto server and catalog-bucket
            moto_endpoint = "http://localhost:8077"
            catalog_bucket = "rs-cluster-catalog"
            export_aws_credentials()
            secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
            # Enable bucket transfer
            os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"
            server = ThreadedMotoServer(port=8077)
            server.start()
            try:
                requests.post(f"{moto_endpoint}/moto-api/reset", timeout=5)
                s3_handler = S3StorageHandler(
                    secrets["accesskey"],
                    secrets["secretkey"],
                    secrets["s3endpoint"],
                    secrets["region"],
                )

                s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)

                # Populate catalog-bucket with files.
                lst_with_files_to_be_copied = ["may24C355000e4102500n.tif"]
                for obj in lst_with_files_to_be_copied:
                    s3_handler.s3_client.put_object(Bucket=catalog_bucket, Key=obj, Body="testing\n")

                expired_items = check_expired_items(connection)
                manage_expired_items(expired_items, connection)

                # Check that the expired item has been correctly updated.
                verify_query = """
                SELECT * FROM items WHERE id = 'expired_item'
                """
                cursor.execute(verify_query)
                result = cursor.fetchall()
                item = result[0]
                assert item[5]["assets"] == {}
                assert item[5]["properties"]["unpublished"] == item[5]["properties"]["updated"]
            except Exception as e:
                raise RuntimeError("error") from e
            finally:
                server.stop()
                clear_aws_credentials()
                os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"

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
            # Close the cursor and connection
            cursor.close()
            connection.close()

    def test_prefect_flow(self):
        run()
