"""Init the FastAPI application."""

from rs_server_cadip.fastapi.cadip_routers import cadip_routers
from rs_server_common.fastapi_app import init_app

# Init the FastAPI application with the cadip routers.
app = init_app(cadip_routers, init_db=True)
