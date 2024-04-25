"""Main package."""

from rs_server_common import settings

# Set automatically by running `poetry dynamic-versioning`
__version__ = "0.0.0"

settings.SERVICE_NAME = "rs.server.adgs"

# Router tags used by the swagger UI
adgs_tags = ["ADGS stations"]
