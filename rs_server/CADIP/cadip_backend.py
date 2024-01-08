"""Docstring will be here."""
from fastapi import FastAPI

from .api import cadu_download, cadu_list

app = FastAPI()
app.include_router(cadu_download.router)
app.include_router(cadu_list.router)


@app.get("/")
async def home():
    """Docstring will be here."""
    return {"message": "Hello World"}
