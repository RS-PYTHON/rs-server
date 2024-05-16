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

"""CadipDownloadStatus implementation."""

from __future__ import annotations

from rs_server_common.db.models.download_status import DownloadStatus, EDownloadStatus
from sqlalchemy import Column, Enum


class CadipDownloadStatus(DownloadStatus):
    """Database model implementation for CADU products download status from CADIP stations."""

    __tablename__ = "cadip_download_status"

    # I have errors when implementing the enum field in the parent class, I don't know why
    status: EDownloadStatus = Column(Enum(EDownloadStatus), default=EDownloadStatus.NOT_STARTED)

    def __init__(self, *args, status: EDownloadStatus = EDownloadStatus.NOT_STARTED, **kwargs):
        """Invoked when creating a new record in the database table."""
        super().__init__(*args, **kwargs)
        self.status = status
