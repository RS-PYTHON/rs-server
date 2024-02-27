"""Store diverse objects and values used throughout the application."""

from os import environ as env

from httpx import AsyncClient

##############
# Local mode #
##############

# The local mode flag is defined in an environment variable
__local_mode: bool = False
try:
    env_var = env["RSPY_LOCAL_MODE"].lower()
    __local_mode = (env_var == "1") or (env_var[0] == "t") or (env_var[0] == "y")
except (IndexError, KeyError):
    pass


def local_mode():
    """Get local mode flag"""
    return __local_mode


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
