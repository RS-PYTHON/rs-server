"""Test database implementation"""

from contextlib import contextmanager
from datetime import datetime

import pytest

from rs_server.CADIP.models.cadu_download_status import (
    CaduDownloadStatus,
    EDownloadStatus,
)
from rs_server.db.database import get_db


def test_cadu_download_status(database):
    """
    Test CADU product download status database operations.

    :param database: database fixture set in conftest.py
    """

    # Define a few values for our tests
    cadu_id1 = "cadu_id_1"
    cadu_id2 = "cadu_id_2"
    NAME1 = "product 1"
    NAME2 = "product 2"
    DATE1 = datetime(2024, 1, 1)
    DATE2 = datetime(2024, 1, 2)
    DATE3 = datetime(2024, 1, 3)
    DATE4 = datetime(2024, 1, 4)
    DATE5 = datetime(2024, 1, 5)

    # Open a database connection
    with contextmanager(get_db)() as db:
        # Add two new download status to database
        created1 = CaduDownloadStatus.create(db=db, cadu_id=cadu_id1, name=NAME1, available_at_station=DATE1)
        created2 = CaduDownloadStatus.create(db=db, cadu_id=cadu_id2, name=NAME2, available_at_station=DATE2)

        # Check that e auto-incremented database IDs were given
        assert created1.db_id == 1
        assert created2.db_id == 2

        # Check that creating a new product with the same name will raise an exception.
        # Do it in a specific database session because the exception will close the session.
        with contextmanager(get_db)() as db_exception, pytest.raises(
            Exception,
            match="duplicate key value violates unique constraint",
        ):
            CaduDownloadStatus.create(db=db_exception, cadu_id=cadu_id1, name=NAME1, available_at_station=DATE1)

        # Get all products from database
        products = CaduDownloadStatus.get_all(db=db)

        # Check they have same values than those returned by the create operation
        assert len(products) == 2
        for created, read1 in zip([created1, created2], products):
            assert created.cadu_id == read1.cadu_id
            assert created.name == read1.name

        # Get product by CADU ID and name, check that the database ID is consistent
        read1 = CaduDownloadStatus.get(cadu_id=created1.cadu_id, name=created1.name, db=db)
        assert created1.db_id == read1.db_id

        # Start download
        created1.in_progress(db, download_start=DATE3)

        # All the Python variables linking on the same SQL instance have been updated
        assert created1.status == read1.status == EDownloadStatus.IN_PROGRESS
        assert created1.download_start == read1.download_start == DATE3

        # Download done
        created1.done(db, download_stop=DATE4)
        assert created1.status == read1.status == EDownloadStatus.DONE
        assert created1.download_stop == read1.download_stop == DATE4

        # created1 failed
        fail_message = "Failed because ..."
        created1.failed(db, fail_message, download_stop=DATE5)
        assert created1.status == read1.status == EDownloadStatus.FAILED
        assert created1.status_fail_message == read1.status_fail_message == fail_message
        assert created1.download_stop == read1.download_stop == DATE5


# from sqlalchemy.sql import text
# db.execute(text("select * from cadu_products"))
