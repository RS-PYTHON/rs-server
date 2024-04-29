"""Unit tests for OpenTelemetry."""

from fastapi import FastAPI
from rs_server_common.utils import opentelemetry
from rs_server_common.utils.logging import Logging


async def test_opentelemetry(monkeypatch):
    """
    For now, just test that the otel init code passes without errors.
    Don't check the generated logs, traces and metrics.
    """

    monkeypatch.setenv("LOKI_ENDPOINT", "http://dummy:1234")
    monkeypatch.setenv("TEMPO_ENDPOINT", "http://dummy:1234")

    Logging.default(__name__)
    app = FastAPI()
    opentelemetry.init_traces(app, "pytest")
