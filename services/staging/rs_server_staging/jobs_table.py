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

"""Module used to implement abstract model of an SQLAlchemy table."""

from __future__ import annotations

import enum
from threading import Lock

from pygeoapi.util import JobStatus
from rs_server_staging import Base
from sqlalchemy import Column, DateTime, Enum, Integer, String, func, orm

# pylint: disable=attribute-defined-outside-init
# mypy: ignore-errors
# Ignore pylint and mypy false positive errors on sqlalchemy


class JobType(enum.Enum):
    """
    Enum for the job type specified in OGC API Processes specification
    """

    #  From the specification
    process = "process"  # pylint: disable=invalid-name


class JobsTable(Base):  # pylint: disable=too-few-public-methods
    """
    Abstract implementation of SQLAlchemy Base

    Must be kept in line with
    https://github.com/geopython/pygeoapi/blob/master/tests/data/postgres_manager_full_structure.backup.sql
    """

    __tablename__ = "jobs"

    type = Column(Enum(JobType), nullable=False, server_default=JobType.process.value)
    identifier = Column(String, primary_key=True, unique=True, index=True)
    processID = Column(String, nullable=False)
    status = Column(Enum(JobStatus), nullable=False)
    progress = Column(Integer, server_default="0", nullable=False)
    # Pylint issue with func.now, check this: https://github.com/sqlalchemy/sqlalchemy/issues/9189
    created = Column(DateTime, server_default=func.now())  # pylint: disable=not-callable
    started = Column(DateTime, server_default=func.now())  # pylint: disable=not-callable
    finished = Column(DateTime)  # pylint: disable=not-callable
    # onupdate=func.now(), server_onupdate=func.now() is not working, did not figure why
    # instead, force the PostgreSQLManager from pygeoapi to update the updated column specifically with
    # update_job function (check processors.py log_job_execution function)
    updated = Column(
        DateTime,
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
        server_onupdate=func.now(),  # pylint: disable=not-callable
    )
    location = Column(String)
    mimetype = Column(String)
    message = Column(String)

    def __init__(self, *args, **kwargs):
        """Invoked when creating a new record in the database table."""
        super().__init__(*args, **kwargs)
        self.lock = Lock()

    @orm.reconstructor
    def init_on_load(self):
        """Invoked when retrieving an existing record from the database table."""
        self.lock = Lock()
