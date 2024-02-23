"""Init the FastAPI application."""

from rs_server_common.fastapi_app import init_app
from rs_server_frontend.fastapi.frontend_routers import frontend_routers

#
# NOTE: the frontend endpoints are inefficient and won't never be called because Ingress redirects
# the adgs, cadip, ... endpoints to the adgs, cadip, ... services that run on other pods and containers.
# So we don't have to initiate the database.
#
# TODO: find a way to copy the service endpoint declarations, without any implementation (because the frontend
# implementation will never be called) and without pulling the service dependencies.
#
# Init the FastAPI application with the routers.
app = init_app(frontend_routers, init_db=False)
