"""FastAPI"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from rs_server import OPEN_DB_SESSION
from rs_server.CADIP.api import cadu_download, cadu_list, cadu_status
from rs_server.db.database import sessionmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Open database session
    if OPEN_DB_SESSION:
        sessionmanager.open_session()

    yield

    # Close database session when the FastAPI server closes.
    if sessionmanager._engine is not None:
        await sessionmanager.close()


app = FastAPI(title="RS FastAPI server", lifespan=lifespan)

app.include_router(cadu_download.router)
app.include_router(cadu_list.router)
app.include_router(cadu_status.router)


@app.get("/")
async def home():
    """Home endpoint."""
    return {"message": "RS server home endpoint"}
