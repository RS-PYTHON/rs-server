"""Store diverse objects and values used throughout the application."""

import os

from httpx import AsyncClient

#########################
# Environment variables #
#########################


def env_bool(var: str, default: bool) -> bool:
    """
    Return True if an environemnt variable is set to 1, true or yes (case insensitive).
    Return False if set to 0, false or no (case insensitive).
    Return the default value if not set or set to a different value.
    """
    val = os.getenv(var, str(default)).lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return True
    if val in ("n", "no", "f", "false", "off", "0"):
        return False
    return default


# True if the 'RSPY_LOCAL_MODE' environemnt variable is set to 1, true or yes (case insensitive).
# By default: if not set or set to a different value, return False.
local_mode = env_bool("RSPY_LOCAL_MODE", False)

# Cluster mode is the opposite of local mode
cluster_mode = not local_mode


###############
# HTTP client #
###############

__http_client: AsyncClient | None = None


def http_client():
    """Get HTTP client"""
    return __http_client


def set_http_client(value):
    """Set HTTP client"""
    global __http_client  # pylint: disable=global-statement
    __http_client = value


async def del_http_client():
    """Close and delete HTTP client."""
    global __http_client  # pylint: disable=global-statement
    if __http_client:
        await __http_client.aclose()
    __http_client = None
