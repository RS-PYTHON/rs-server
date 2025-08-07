# rs_server_prip/fastapi/prip_app.py

from fastapi import FastAPI

from rs_server_prip.api.prip_search import MockPgstacPrip

from rs_server_prip.fastapi.prip_routers import prip_routers
from rs_server_common.fastapi_app import init_app
from rs_server_common.utils.error_handlers import register_stac_exception_handlers


app = init_app("0.1.0", prip_routers, router_prefix="/prip")

# Set properties for the prip service
app.state.get_connection = MockPgstacPrip.get_connection
app.state.readpool = MockPgstacPrip.readpool()


register_stac_exception_handlers(app)
