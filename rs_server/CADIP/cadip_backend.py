"""Docstring will be here."""
from fastapi import FastAPI

from rs_server.CADIP.api import status
from rs_server.fastapi import app

from .api import download_chunk, list_cadu

app.include_router(list_cadu.router)
app.include_router(download_chunk.router)
app.include_router(status.router)
