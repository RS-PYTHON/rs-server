"""Module used to configure pytests."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(name="staging_client")
def client_():
    """set pygeoapi env variables and init fastapi client app."""
    # To be updated
    geoapi_cfg = Path("rs_server_staging/config/config.yml").absolute()
    openapi_json = Path("rs_server_staging/config/openapi.json").absolute()
    #
    os.environ["PYGEOAPI_CONFIG"] = str(geoapi_cfg)
    os.environ["PYGEOAPI_OPENAPI"] = str(openapi_json)
    from ..rs_server_staging.main import app  # pylint: disable=import-outside-toplevel

    # Test the FastAPI application, opens the database session
    with TestClient(app) as client:
        yield client
