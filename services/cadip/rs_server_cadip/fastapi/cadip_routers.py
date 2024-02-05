"""FastAPI routers definition."""

from rs_server_cadip.api import cadip_download, cadip_search, cadip_status

cadip_routers = [
    cadip_download.router,
    cadip_search.router,
    cadip_status.router,
]
