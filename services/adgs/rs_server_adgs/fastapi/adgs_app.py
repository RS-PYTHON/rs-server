"""Init the FastAPI application."""

from rs_server_adgs.fastapi.adgs_routers import adgs_routers
from rs_server_common.fastapi_app import init_app

# Init the FastAPI application with the adgs routers.
app = init_app(adgs_routers, init_db=True)
