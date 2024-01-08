"""FastAPI service initialisation."""

from fastapi import FastAPI

app = FastAPI(title="RS server FastAPI")


@app.get("/")
async def home():
    """Home endpoint."""
    return {"message": "RS server home endpoint"}
