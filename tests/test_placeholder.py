"""Test placeholder."""

import pytest


@pytest.mark.unit
@pytest.mark.integration
def test_placeholder():
    """Fake test.

    This a fake test to make the CI pass
    because pytest exit in error (exit code : 5) if no test is found.
    It will be removed once true tests are implemented.
    """
    # TODO remove this test once a unit test AND an integration test have been implemented.
    assert True
