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

"""Pydantic schemas for DownloadStatus."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer
from rs_server_common.db.models.download_status import EDownloadStatus


class DownloadStatusBase(BaseModel):
    """DownloadStatus fields that are known when both reading and creating the object."""

    product_id: str
    name: str
    available_at_station: datetime | None


class ReadDownloadStatus(DownloadStatusBase):
    """DownloadStatus fields that are known when reading but not when creating the object."""

    db_id: int
    download_start: datetime | None = None
    download_stop: datetime | None = None
    status: EDownloadStatus
    status_fail_message: str | None = None

    model_config = ConfigDict(
        from_attributes=True,
        validate_default=True,
        use_enum_values=True,
    )

    @field_serializer("available_at_station", "download_start", "download_stop")
    def serialize_dt(self, dt: datetime | None, _info):
        """
        Called by the HTTP endpoint to convert a datetime into a JSON string.
        """
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") if dt else None
