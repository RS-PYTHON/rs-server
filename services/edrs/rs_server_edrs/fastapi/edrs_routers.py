# Copyright 2025 CS Group
# Licensed under the Apache License, Version 2.0

"""FastAPI routers list for EDRS service."""

from rs_server_edrs.api import edrs_endpoints

edrs_routers = [
    edrs_endpoints.router,
]
