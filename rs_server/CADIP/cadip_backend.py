"""Docstring will be here."""
from fastapi import FastAPI

from rs_server.db.crud import cadu_product_crud

from .api import cadu_download, cadu_list, cadu_status

app = FastAPI()
app.include_router(cadu_download.router)
app.include_router(cadu_list.router)
app.include_router(cadu_status.router)

# Include the cadu database endpoints
app.include_router(cadu_product_crud.router)


@app.get("/")
async def home():
    """Docstring will be here."""
    return {"message": "Hello World"}
