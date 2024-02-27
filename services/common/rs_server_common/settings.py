"""Store diverse objects and values used throughout the application."""

from os import environ as env

from httpx import AsyncClient

##############
# Local mode #
##############

# The local mode flag is defined in an environment variable
__local_mode: bool = False
try:
    value = env["RSPY_LOCAL_MODE"].lower()
    __local_mode = (value == "1") or (value[0] == "t") or (value[0] == "y")
except (IndexError, KeyError):
    pass


def local_mode():
    """Get local mode flag"""
    return __local_mode


###############
# HTTP client #
###############

__http_client: AsyncClient = None


def http_client():
    """Get HTTP client"""
    return __http_client


def set_http_client(value):
    """Set HTTP client"""
    global __http_client
    __http_client = value


async def del_http_client():
    """Close and delete HTTP client."""
    global __http_client
    await __http_client.aclose()
    __http_client = None
