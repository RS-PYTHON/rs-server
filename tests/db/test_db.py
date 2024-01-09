"""Test database implementation"""

from contextlib import asynccontextmanager
from datetime import datetime

import pytest

from rs_server.CADIP.models.cadu_download_status import CaduDownloadStatus
from rs_server.db.database import get_db


async def test_cadu_download_status(database):
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
    async with asynccontextmanager(get_db)() as db:
        # Add two new download status to database
        created1 = await CaduDownloadStatus.create(db=db, cadu_id=cadu_id1, name=NAME1, available_at_station=DATE1)
        created2 = await CaduDownloadStatus.create(db=db, cadu_id=cadu_id2, name=NAME2, available_at_station=DATE2)

        # Check that e auto-incremented database IDs were given
        assert created1.db_id == 1
        assert created2.db_id == 2

        # Check that creating a new product with the same name will raise an exception.
        # Do it in a specific database session because the exception will close the session.
        async with asynccontextmanager(get_db)() as db_exception, pytest.raises(
            Exception,
            match="duplicate key value violates unique constraint",
        ):
            await CaduDownloadStatus.create(db=db_exception, cadu_id=cadu_id1, name=NAME1, available_at_station=DATE1)

        # Get all products from database
        products = crud.get_all_products(db=db)

        # Check they have same values than those returned by the create operation
        assert len(products) == 2
        for created, read1 in zip([created1, created2], products):
            assert created.id == read1.id
            assert created.name == read1.name

        # Get product by ID, check that the name is consistent
        read1 = crud.get_product_by_id(db=db, product_id=created1.id)
        assert created1.name == read1.name

        # Start download
        updated1 = crud.product_download_start(
            db=db,
            product_id=created1.id,
            info=CaduProductDownloadStart(downlink_start=DATE3),
        )

        # All the Python variables linking on the same SQL instance have been updated
        assert created1.status == CaduDownloadStatus.IN_PROGRESS
        assert read1.status == CaduDownloadStatus.IN_PROGRESS
        assert updated1.status == CaduDownloadStatus.IN_PROGRESS
        assert created1.downlink_start == DATE3

        # Download done
        updated1 = crud.product_download_done(
            db=db,
            product_id=created1.id,
            info=CaduProductDownloadDone(downlink_stop=DATE4),
        )
        assert created1.status == CaduDownloadStatus.DONE
        assert created1.downlink_stop == DATE4

        # Download failed
        fail_message = "Failed because ..."
        updated1 = crud.product_download_fail(
            db=db,
            product_id=created1.id,
            info=CaduProductDownloadFail(downlink_stop=DATE5, status_fail_message=fail_message),
        )
        assert created1.status == CaduDownloadStatus.FAILED
        assert created1.downlink_stop == DATE5
        assert created1.status_fail_message == fail_message

        bp = 0


# from sqlalchemy.sql import text
# db.execute(text("select * from cadu_products"))
