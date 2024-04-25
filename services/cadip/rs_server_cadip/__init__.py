"""Main package."""

from rs_server_common import settings

# Set automatically by running `poetry dynamic-versioning`
__version__ = "0.0.0"

settings.SERVICE_NAME = "rs.server.cadip"

# Router tags used by the swagger UI
cadip_tags = ["CADIP stations"]
