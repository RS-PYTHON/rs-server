"""FastAPI routers definition."""

from rs_server_cadip.api import cadu_download, cadu_search, cadu_status

cadip_routers = [
    cadu_download.router,
    cadu_search.router,
    cadu_status.router,
]
