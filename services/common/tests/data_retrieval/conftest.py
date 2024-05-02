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

"""Common fixtures for data retrieval."""

from datetime import datetime

import pytest


@pytest.fixture(scope="session")
def start() -> datetime:
    """
    This fixture returns a datetime object representing the start time for testing scenarios.

    Returns:
        datetime: A datetime object representing the start time.

    """
    return datetime(2022, 1, 1)


@pytest.fixture(scope="session")
def end() -> datetime:
    """
    This fixture returns a datetime object representing the end time for testing scenarios.

    Returns:
        datetime: A datetime object representing the end time.

    """
    return datetime(2022, 2, 2)


@pytest.fixture(scope="session")
def in_the_future() -> datetime:
    """
    This fixture returns a datetime object representing a date in the future for testing scenarios.

    Returns:
        datetime: A datetime object representing a date in the future.

    """
    return datetime(2222, 1, 1)
