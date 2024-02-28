"""FastAPI routers definition."""

from rs_server_adgs.api import adgs_download, adgs_search, adgs_status

adgs_routers = [
    adgs_search.router,
    adgs_download.router,
    adgs_status.router,
]
