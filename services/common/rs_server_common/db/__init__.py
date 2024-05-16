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

"""
Database modules.

See tutorials:
https://fastapi.tiangolo.com/tutorial/sql-databases/
https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
https://medium.com/@tclaitken/setting-up-a-fastapi-app-with-async-sqlalchemy-2-0-pydantic-v2-e6c540be4308
"""

from sqlalchemy.orm import declarative_base

# Construct a sqlalchemy base class for declarative class definitions.
Base = declarative_base()
