from __future__ import annotations
import warnings

from rs_server_edrs import __version__
from rs_server_edrs.fastapi.edrs_routers import edrs_routers

from rs_server_common.fastapi_app import init_app
from rs_server_common.utils.error_handlers import register_stac_exception_handlers

from rs_server_edrs.api.edrs_endpoints import MockPgstacEdrs

warnings.filterwarnings("ignore", category=UserWarning, module="stac_pydantic")

app = init_app(__version__, edrs_routers, router_prefix="/edrs")

# pgSTAC hooks (CoreCrudClient expects these)
app.state.get_connection = MockPgstacEdrs.get_connection
app.state.readpool = MockPgstacEdrs.readpool()

register_stac_exception_handlers(app)
