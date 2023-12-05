"""Docstring will be here."""
from fastapi import APIRouter

router = APIRouter()

@router.get("/cadip/{station}/cadu")
def download(station):
    """Docstring will be here."""
    # todo
    pass