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

"""Shared stac-fastapi-pgstac API instance.

Since stac-fastapi-pgstac 6.4.0, the library no longer exposes module-level
``app``/``api``/``settings`` globals (see ``instantiate_api`` in
https://github.com/stac-utils/stac-fastapi-pgstac/releases/tag/6.4.0). This module builds
them once so they can be shared between ``rs_server_catalog.app`` and
``rs_server_catalog.middleware.catalog_middleware`` without a circular import.
"""

from stac_fastapi.pgstac.app import instantiate_api
from stac_fastapi.pgstac.config import Settings

settings = Settings()
api = instantiate_api(settings=settings)
with_transactions = settings.enable_transactions_extensions
