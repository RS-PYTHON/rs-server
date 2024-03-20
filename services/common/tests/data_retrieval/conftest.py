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
