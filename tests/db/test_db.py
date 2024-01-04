"""Test database implementation"""

from contextlib import contextmanager
from datetime import datetime

import pytest
from fastapi import Depends

import rs_server.db.crud.cadu_product_crud as crud
from rs_server.db.models.cadu_product_model import CaduProduct
from rs_server.db.models.download_status import DownloadStatus
from rs_server.db.schemas.cadu_product_schema import (
    CaduProductCreate,
    CaduProductDownloadDone,
    CaduProductDownloadFail,
    CaduProductDownloadStart,
    CaduProductRead,
)
from rs_server.db.session import get_db
from rs_server.db.startup import main_app


# Test all CADU product HTTP operations
def test_cadu_products(database):
    """
    Test CADU products table in database.

    :param database: database fixture set in conftest.py
    """

    # Define a few values for our tests
    NAME1 = "product 1"
    NAME2 = "product 2"
    DATE1 = datetime(2024, 1, 1)
    DATE2 = datetime(2024, 1, 2)
    DATE3 = datetime(2024, 1, 3)
    DATE4 = datetime(2024, 1, 4)
    DATE5 = datetime(2024, 1, 5)

    # We need a database session when calling HTTP operations outside an HTTP client.
    # TODO: call instead ?
    # with TestClient(main_app) as client:
    #     client.get(...
    #     client.post(...
    with contextmanager(get_db)() as db:
        # Clear table records
        db.query(CaduProduct).delete()
        db.commit()

        # Add two new CADU products to database
        created1 = crud.create_product(db=db, product=CaduProductCreate(name=NAME1, available_at_station=DATE1))
        created2 = crud.create_product(db=db, product=CaduProductCreate(name=NAME2, available_at_station=DATE2))

        # The returned products are Python instances
        assert isinstance(created1, CaduProduct)
        assert isinstance(created2, CaduProduct)

        # Check the download status is not started by default
        assert created1.status == DownloadStatus.NOT_STARTED

        # Check that creating a new product with the same name will raise an exception.
        # Do it in a specific database session because it will trigger a rollback and corrupt the old session.
        with contextmanager(get_db)() as db_exception, pytest.raises(
            Exception,
            match="duplicate key value violates unique constraint",
        ):
            crud.create_product(db=db_exception, product=CaduProductCreate(name=NAME1, available_at_station=DATE1))

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
        assert created1.status == DownloadStatus.IN_PROGRESS
        assert read1.status == DownloadStatus.IN_PROGRESS
        assert updated1.status == DownloadStatus.IN_PROGRESS
        assert created1.downlink_start == DATE3

        # Download done
        updated1 = crud.product_download_done(
            db=db,
            product_id=created1.id,
            info=CaduProductDownloadDone(downlink_stop=DATE4),
        )
        assert created1.status == DownloadStatus.DONE
        assert created1.downlink_stop == DATE4

        # Download failed
        fail_message = "Failed because ..."
        updated1 = crud.product_download_fail(
            db=db,
            product_id=created1.id,
            info=CaduProductDownloadFail(downlink_stop=DATE5, status_fail_message=fail_message),
        )
        assert created1.status == DownloadStatus.FAILED
        assert created1.downlink_stop == DATE5
        assert created1.status_fail_message == fail_message

        bp = 0

    bp = 0


# from sqlalchemy.sql import text
# db.execute(text("select * from cadu_products"))
