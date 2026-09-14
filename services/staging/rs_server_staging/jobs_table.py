# Copyright 2023-2026 Airbus, CS Group
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
from typing import Any

from rs_server_staging import Base
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    String,
    func,
    orm,
)
from sqlalchemy.engine import Engine

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

    type = Column(String, nullable=False, server_default=JobType.process.value)
    identifier = Column(String, primary_key=True, unique=True, index=True)
    processID = Column(String, nullable=False)
    status = Column(String, nullable=False)
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


def get_table_model(db_search_path: tuple[str], engine: Engine, table_output: bool) -> Any:
    """Define SQLAlchemy jobs table model.
    Rewrite of function get_table_model from pygeoapi:
    https://github.com/geopython/pygeoapi/blob/f765a64fa65350dc93d9df0a1b38755bef6c31b0/pygeoapi/process/manager/postgresql.py#L306
    Because the model used in pygeoapi is not compatible with ours
    (incompatibility between field names, processID in out case but process_id in pygeoapi)
    """

    schema = db_search_path[0]

    metadata = MetaData()

    jobs = JobsTable.__table__.to_metadata(
        metadata,
        schema=schema,
    )

    if table_output and "output" not in jobs.c:
        jobs.append_column(Column("output", LargeBinary))

    metadata.create_all(
        engine,
        tables=[jobs],
        checkfirst=True,
    )

    return jobs
