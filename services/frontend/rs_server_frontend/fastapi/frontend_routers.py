"""Sub-project routers aggregation."""

from rs_server_adgs.fastapi.adgs_routers import adgs_routers
from rs_server_cadip.fastapi.cadip_routers import cadip_routers

frontend_routers = adgs_routers + cadip_routers
