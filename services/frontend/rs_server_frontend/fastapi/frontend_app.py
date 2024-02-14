"""Init the FastAPI application."""

from rs_server_common.fastapi_app import init_app
from rs_server_frontend.fastapi.frontend_routers import frontend_routers

# Init the FastAPI application with the routers.
app = init_app(frontend_routers, init_db=False)
