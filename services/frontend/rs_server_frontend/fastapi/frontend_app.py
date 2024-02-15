"""Init the FastAPI application."""

from rs_server_common.fastapi_app import init_app
from rs_server_frontend.fastapi.frontend_routers import frontend_routers

# Init the FastAPI application with the routers.
# NOTE: the frontend endpoints are inefficient and won't never be called
# because Ingress redirects the adgs, cadip, ... endpoints to the adgs, cadip, ... services
# that run on other pods and containers.
app = init_app(frontend_routers, init_db=False)
