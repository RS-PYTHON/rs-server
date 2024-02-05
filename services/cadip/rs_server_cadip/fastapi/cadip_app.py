"""Init the FastAPI application."""

# Import the database table modules before initializing the FastAPI,
# that will init the database session and create the tables.
# pylint: disable=unused-import, import-outside-toplevel
# flake8: noqa
import rs_server_cadip.cadip_download_status  # DON'T REMOVE
from rs_server_cadip.fastapi.cadip_routers import cadip_routers
from rs_server_common.fastapi_app import init_app

# Init the FastAPI application with the cadip routers.
app = init_app(cadip_routers, init_db=True)
