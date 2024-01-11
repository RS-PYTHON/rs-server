"""Test database implementation"""

from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from rs_server.CADIP.cadip_backend import app
from rs_server.CADIP.models.cadu_download_status import (
    CaduDownloadStatus,
    EDownloadStatus,
)
from rs_server.db.database import get_db


# pylint: disable=unused-argument,too-many-locals,too-many-statements
def test_cadu_download_status(database):
    """
    Test CADU product download status database operations.

    :param database: database fixture set in conftest.py
    """

    # Define a few values for our tests
    _cadu_id1 = "cadu_id_1"
    _cadu_id2 = "cadu_id_2"
    _cadu_id3 = "cadu_id_3"
    _name1 = "product 1"
    _name2 = "product 2"
    _name3 = "product 3"
    _date1 = datetime(2024, 1, 1)
    _date2 = datetime(2024, 1, 2)
    _date3 = datetime(2024, 1, 3)
    _date4 = datetime(2024, 1, 4)
    _date5 = datetime(2024, 1, 5)

    # Open a database connection
    with contextmanager(get_db)() as db:
        # Add two new download status to database
        created1 = CaduDownloadStatus.get_or_create(db=db, cadu_id=_cadu_id1, name=_name1, available_at_station=_date1)
        created2 = CaduDownloadStatus.get_or_create(db=db, cadu_id=_cadu_id2, name=_name2, available_at_station=_date2)

        # Check that e auto-incremented database IDs were given
        assert created1.db_id == 1
        assert created2.db_id == 2

        # They have different Lock instances
        assert created1.lock != created2.lock

        # Check that creating a new product with the same values will return the existing entry.
        created3 = CaduDownloadStatus.get_or_create(db, cadu_id=_cadu_id1, name=_name1, available_at_station=_date1)
        assert created1.db_id == created3.db_id

        # The entry returned by the same database session has the same Lock instance
        assert created1.lock == created3.lock

        # But the entry returned by a different session has a different Lock instance
        with contextmanager(get_db)() as db2:
            created4 = CaduDownloadStatus.get_or_create(
                db2,
                cadu_id=_cadu_id1,
                name=_name1,
                available_at_station=_date1,
            )
            assert created1.db_id == created4.db_id
            assert created1.lock != created4.lock

        # Test error when entry is missing. Use a distinct database session because it will be closed after exception.
        with contextmanager(get_db)() as db_exception, pytest.raises(
            HTTPException,
            match="404: No CaduDownloadStatus entry found",
        ):
            CaduDownloadStatus.get(db_exception, cadu_id=_cadu_id3, name=_name3)

        # Test the http endpoint
        client = TestClient(app)
        url = "/cadip/CADIP/cadu/status?cadu_id={cadu_id}&name={name}"

        # Read an existing entry
        response = client.get(url.format(cadu_id=_cadu_id1, name=_name1))
        assert response.status_code == 200
        assert response.json()["db_id"] == created1.db_id

        # Read a missing entry
        response = client.get(url.format(cadu_id=_cadu_id3, name=_name3))
        assert response.status_code == 404
        assert response.json()["detail"].startswith("No CaduDownloadStatus entry found")

        # Get all products from database
        products = CaduDownloadStatus.get_all(db=db)

        # Check they have same values than those returned by the create operations
        assert len(products) == 2
        for created, read1 in zip([created1, created2], products):
            assert created.cadu_id == read1.cadu_id
            assert created.name == read1.name

        # Get product by CADU ID and name, check that the database ID is consistent
        read1 = CaduDownloadStatus.get(cadu_id=created1.cadu_id, name=created1.name, db=db)
        assert created1.db_id == read1.db_id

        # Start download
        created1.in_progress(db, download_start=_date3)

        # All the Python variables linking on the same SQL instance have been updated
        assert created1.status == read1.status == EDownloadStatus.IN_PROGRESS
        assert created1.download_start == read1.download_start == _date3

        # Download done
        created1.done(db, download_stop=_date4)
        assert created1.status == read1.status == EDownloadStatus.DONE
        assert created1.download_stop == read1.download_stop == _date4

        # created1 failed
        fail_message = "Failed because ..."
        created1.failed(db, fail_message, download_stop=_date5)
        assert created1.status == read1.status == EDownloadStatus.FAILED
        assert created1.status_fail_message == read1.status_fail_message == fail_message
        assert created1.download_stop == read1.download_stop == _date5


# from sqlalchemy.sql import text
# db.execute(text("select * from cadu_products"))
