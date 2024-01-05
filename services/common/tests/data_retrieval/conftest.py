"""Common fixtures for data retrieval."""
from datetime import datetime

import pytest


@pytest.fixture(scope="session")
def start() -> datetime:
    return datetime(2022, 1, 1)


@pytest.fixture(scope="session")
def end() -> datetime:
    return datetime(2022, 2, 2)


@pytest.fixture(scope="session")
def in_the_future() -> datetime:
    return datetime(2222, 1, 1)
