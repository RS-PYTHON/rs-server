"""Init a root FastAPI application from all the sub-project routers."""
from rs_server_adgs.fastapi.adgs_routers import adgs_routers
from rs_server_cadip.fastapi.cadip_routers import cadip_routers
from rs_server_common.fastapi_app import init_app as init_app_with_args


def init_app():
    """Run all routers for the tests."""
    routers = adgs_routers + cadip_routers
    return init_app_with_args(api_version="test", routers=routers, init_db=True, pause=3, timeout=6)
