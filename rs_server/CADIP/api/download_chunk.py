"""Docstring will be here."""
from eodag import EODataAccessGateway, EOProduct
from fastapi import APIRouter

router = APIRouter()


@router.get("/cadip/{station}/cadu")
def download(station: str, chunk_id: str = ""):
    """Docstring will be here."""
    dag_client = init_eodag(station)
    eop = init_eop(chunk_id)
    dag_client.download(eop)
    return {"Path": eop.location}


def init_eodag(station):
    """Docstring will be here."""
    config_file_path = "CADIP/library/cadip_ws_config.yaml"
    eodag = EODataAccessGateway(config_file_path)
    eodag.set_preferred_provider(station)
    return eodag


def init_eop(file_id: str):
    """Docstring will be here."""
    properties = {
        "title": "Name",
        "id": file_id,
        "geometry": "POLYGON((180 -90, 180 90, -180 90, -180 -90, 180 -90))",
        "downloadLink": f"http://127.0.0.1:5000/Files({file_id})/$value",
    }
    product = EOProduct("CADIP", properties)
    # product.register_downloader()
    return product
