import pytest
from rs_server_frontend.main import app
from starlette.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as the_client:
        yield the_client
