"""Init a root FastAPI application from all the sub-project routers."""

from rs_server_common.fastapi_app import init_app as init_app_with_args
from rs_server_frontend.fastapi.frontend_routers import frontend_routers


def init_app():
    """Run all routers for the tests. The frontend already does that."""
    return init_app_with_args(routers=frontend_routers, init_db=True, pause=3, timeout=6)
