"""FastAPI"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rs_server.CADIP.api import status
from rs_server.db.database import sessionmanager

from .api import cadu_download, cadu_list, cadu_status

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if sessionmanager._engine is not None:
        await sessionmanager.close()


app = FastAPI(title="RS FastAPI server", lifespan=lifespan)

app.include_router(cadu_download.router)
app.include_router(cadu_list.router)
app.include_router(cadu_status.router)

app.include_router(status.router)


@app.get("/")
async def home():
    """Home endpoint."""
    return {"message": "RS server home endpoint"}
