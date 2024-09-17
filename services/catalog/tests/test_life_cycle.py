"""Tests for life cycle catalog."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from rs_server_catalog.lifecycle import check_expired_items


def test_check_expired_items(db_url):
    """test the check expired items function."""
    # Connect to the PostgreSQL database
    connection = psycopg2.connect(db_url)
    now = datetime.now(ZoneInfo("UTC"))
    expired_date = (now - timedelta(days=30)).isoformat() + "Z"

    try:
        # Create a cursor to execute the query
        cursor = connection.cursor()

        # Utilisez une date dans le passé pour datetime
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
                    "href": "s3://temp-bucket/toto_S1_L1/images/may24C355000e4102500n.tif",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "title": "NOAA STORM COG",
                },
            },
            "stac_extensions": [
                "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
                "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
            ],
        }

        cursor.execute("""ALTER TABLE _items_1 DROP CONSTRAINT _items_1_dt""")

        cursor.execute(
            """
            INSERT INTO items (id, collection, geometry, datetime, end_datetime, content)
            VALUES (%s, %s, %s, %s, %s, %s)
        """,
            (
                item["id"],
                item["collection"],
                json.dumps(item["geometry"]),
                past_date,
                now,
                json.dumps(
                    {
                        "bbox": item["bbox"],
                        "assets": item["assets"],
                        "properties": item["properties"],
                        "stac_extensions": item["stac_extensions"],
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
        cursor.execute(verify_query, (item["id"],))
        inserted_item = cursor.fetchone()

        if inserted_item:
            print("Inserted item found:", inserted_item)
        else:
            print("No item found with the given ID.")

    except Exception as e:
        print("Une erreur s'est produite :", e)
        connection.rollback()

    finally:
        # Close the cursor and connection
        cursor.close()
        connection.close()
    expired_items = check_expired_items(database_url=db_url)
    assert len(expired_items) == 1
