"""Docstring will be here."""
from fastapi import FastAPI

from rs_server.db.crud import cadu_product_crud

from .api import download_chunk, list_cadu

app = FastAPI()  # TODO maybe implement the root FastAPI object elsewhere in a root module
app.include_router(list_cadu.router)
app.include_router(download_chunk.router)

# Include the cadu database endpoints
app.include_router(cadu_product_crud.router)


@app.get("/")
async def home():
    """Docstring will be here."""
    return {"message": "Hello World"}
