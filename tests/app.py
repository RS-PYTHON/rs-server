"""Init a root FastAPI application from all the sub-project routers."""

from rs_server_common.fastapi_app import init_app
from rs_server_frontend.fastapi.frontend_routers import frontend_routers

# Run all routers for the tests. The frontend already does that.
routers = frontend_routers
app = init_app(routers, init_db=True, pause=3, timeout=6)
