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

"""Test database implementation"""

from contextlib import contextmanager
from datetime import datetime

import pytest
import sqlalchemy
from fastapi import HTTPException
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_cadip.cadip_download_status import CadipDownloadStatus, EDownloadStatus
from rs_server_common.db.database import get_db


# pylint: disable=unused-argument,too-many-locals,too-many-statements
@pytest.mark.parametrize(
    "cls, type_, url_prefix",
    [[CadipDownloadStatus, "cadip", "/cadip/CADIP/cadu"], [AdgsDownloadStatus, "adgs", "/adgs/aux"]],
    ids=[CadipDownloadStatus, AdgsDownloadStatus],
)
def test_download_status(client, cls, type_, url_prefix):
    """
    Test product download status database operations.

    :param client: client fixture set in conftest.py
    """

    # Define a few values for our tests: products ID, name and some dates
    _pid1 = f"{type_}_id_1"
    _pid2 = f"{type_}_id_2"
    _pid3 = f"{type_}_id_3"
    _name1 = f"{type_} name 1"
    _name2 = f"{type_} name 2"
    _name3 = f"{type_} name 3"
    _date1 = datetime(2024, 1, 1)
    _date2 = datetime(2024, 1, 2)
    _date3 = datetime(2024, 1, 3)
    _date4 = datetime(2024, 1, 4)
    _date5 = datetime(2024, 1, 5)

    # Open a database connection
    with contextmanager(get_db)() as db:
        # Add two new download status to database
        created1 = cls.create(db=db, product_id=_pid1, name=_name1, available_at_station=_date1)
        created2 = cls.create(db=db, product_id=_pid2, name=_name2, available_at_station=_date2)

        # Check that e auto-incremented database IDs were given
        assert created1.db_id == 1
        assert created2.db_id == 2

        # They have different Lock instances
        assert created1.lock != created2.lock

        # Change download status to in_progress and update the database
        created1.in_progress(db=db)

        # Check that getting the product from database with the same values will return the existing entry.
        read1 = cls.get(db, name=_name1)
        assert created1.db_id == read1.db_id
        assert created1.status == EDownloadStatus.IN_PROGRESS

        # The entry returned by the same database session has the same Lock instance
        assert created1.lock == read1.lock

        # But the entry returned by a different session has a different Lock instance
        with contextmanager(get_db)() as db2:
            read2 = cls.get(db2, name=_name1)
            assert created1.db_id == read2.db_id
            assert created1.lock != read2.lock

            # Also change the download status again from this database session
            assert created1.status == read2.status
            read2.done(db=db2)

        # And check that it was updated from this other session
        assert cls.get(db, name=_name1).status == EDownloadStatus.DONE

        # Check that creating a new product with the same values will raise an exception.
        # Use a distinct database session because it will be closed after exception.
        with contextmanager(get_db)() as db_exception, pytest.raises(
            sqlalchemy.exc.IntegrityError,
            match="duplicate key value violates unique constraint",
        ):
            cls.create(db_exception, product_id=_pid1, name=_name1, available_at_station=_date1)

        # Test error when entry is missing.
        with contextmanager(get_db)() as db_exception, pytest.raises(
            HTTPException,
            match=f"404: No {cls.__name__} entry found",
        ):
            cls.get(db_exception, name=_name3)

        # Test the http endpoint
        url = f"{url_prefix}/status"

        # Read an existing entry
        response = client.get(url, params={"product_id": _pid1, "name": _name1})
        assert response.status_code == 200
        data = response.json()
        assert data["db_id"] == created1.db_id

        # Check that the status is returned as a string in the JSON response
        assert data["status"] == "DONE"

        # Check the dates format
        date_format = "%Y-%m-%dT%H:%M:%S.%f"
        for date in "available_at_station", "download_start", "download_stop":
            datetime.strptime(data[date], date_format)

        # If e.g. the microseconds were missing, it would raise an Exception
        with pytest.raises(ValueError, match="does not match format"):
            datetime.strptime("2024-01-01T00:00:00", date_format)

        # Read a missing entry
        response = client.get(url, params={"product_id": _pid3, "name": _name3})
        assert response.status_code == 404
        assert response.json()["detail"].startswith(f"No {cls.__name__} entry found")

        # Get product by product ID and name, check that the database ID is consistent
        read1 = cls.get(name=created1.name, db=db)
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
