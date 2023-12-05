"""Docstring will be here."""
from .api import download_chunk, list_cadu
from fastapi import FastAPI

app = FastAPI()
app.include_router(list_cadu.router)
app.include_router(download_chunk.router)

@app.get("/")
async def home():
    """Docstring will be here."""
    return {"message": "Hello World"}