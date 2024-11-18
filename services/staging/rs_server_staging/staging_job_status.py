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

from rs_server_common.db import Base
from sqlalchemy import Column, DateTime, Enum, Float, String, func, orm

# pylint: disable=attribute-defined-outside-init
# mypy: ignore-errors
# Ignore pylint and mypy false positive errors on sqlalchemy


class EStagingStatus(str, enum.Enum):
    """
    Staging status enumeration.
    """

    QUEUED = "queued"  # Request received, processor will start soon
    CREATED = "created"  # Processor has been initialised
    STARTED = "started"  # Processor execution has started
    IN_PROGRESS = "in_progress"  # Processor execution is in progress
    STOPPED = "stopped"
    FAILED = "failed"
    FINISHED = "finished"
    PAUSED = "paused"
    RESUMED = "resumed"
    CANCELLED = "cancelled"

    def __str__(self):
        return self.value


class StagingJobStatus(Base):  # pylint: disable=too-few-public-methods
    """Abstract implementation of SQLAlchemy Base"""

    __tablename__ = "jobs"

    identifier = Column(String, primary_key=True, unique=True, index=True)
    status = Column(Enum(EStagingStatus), nullable=False)
    progress = Column(Float, server_default="0.0")
    # Pylint issue with func.now, check this: https://github.com/sqlalchemy/sqlalchemy/issues/9189
    created_at = Column(DateTime, server_default=func.now())  # pylint: disable=not-callable
    # onupdate=func.now(), server_onupdate=func.now() is not working, did not figure why
    # instead, force the PostgresqlManager from pygeoapi to update the updated_at column specifically with
    # update_job function (check processors.py log_job_execution function)
    updated_at = Column(
        DateTime,
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
        server_onupdate=func.now(),  # pylint: disable=not-callable
    )
    detail = Column(String)

    def __init__(self, *args, **kwargs):
        """Invoked when creating a new record in the database table."""
        super().__init__(*args, **kwargs)
        self.lock = Lock()

    @orm.reconstructor
    def init_on_load(self):
        """Invoked when retrieving an existing record from the database table."""
        self.lock = Lock()
