# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
LOCAL_MODE: bool = env_bool("RSPY_LOCAL_MODE", False)

# Cluster mode is the opposite of local mode
CLUSTER_MODE: bool = not LOCAL_MODE

###################
# Other variables #
###################

# Service name for logging and OpenTelemetry
SERVICE_NAME: str | None = None


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
