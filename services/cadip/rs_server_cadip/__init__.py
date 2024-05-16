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

"""Main package."""

from rs_server_common import settings

# Set automatically by running `poetry dynamic-versioning`
__version__ = "0.0.0"

settings.SERVICE_NAME = "rs.server.cadip"

# Router tags used by the swagger UI
cadip_tags = ["CADIP stations"]
