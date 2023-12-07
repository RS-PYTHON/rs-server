"""Docstring will be here."""
import json

from eodag import EODataAccessGateway
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/cadip/{station}/cadu/list")
async def list_cadu_handler(station: str, start_date: str = "", stop_date: str = ""):
    """Docstring will be here."""
    if not get_station_ws(station):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Bad station identifier")
    if start_date and stop_date:
        # prepare start_stop
        dag_client = init_eodag(station)
        products, number = dag_client.search(start=start_date, end=stop_date, provider=station)
    return JSONResponse(status_code=status.HTTP_200_OK, content={station: prepare_products(products)})


def get_station_ws(station: str):
    """Docstring will be here."""
    stations_data = json.loads(open("src/CADIP/library/stations_cfg.json").read())
    return stations_data.get(station.upper(), None)


def init_eodag(station):
    """Docstring will be here."""
    config_file_path = "src/CADIP/library/cadip_ws_config.yaml"
    eodag = EODataAccessGateway(config_file_path)
    eodag.set_preferred_provider(station)
    return eodag


def prepare_products(products_list):
    """Docstring will be here."""
    if not products_list:
        return []
    return [(product.properties["id"], product.properties["Name"]) for product in products_list]
