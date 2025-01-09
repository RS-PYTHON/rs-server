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

"""
This module is used to share common functions between apis endpoints.
Split it from utils.py because of dependency conflicts between rs-server-catalog and rs-server-common.
"""

import asyncio
import functools
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException
from filelock import FileLock
from typing_extensions import Annotated, Doc


@dataclass
class AuthInfo:
    """User authentication information in KeyCloak."""

    # User login (preferred username)
    user_login: str

    # IAM roles
    iam_roles: list[str]

    # Configuration associated to the API key (not implemented for now)
    apikey_config: dict


def log_http_exception(
    logger,
    status_code: Annotated[
        int,
        Doc(
            """
                HTTP status code to send to the client.
                """,
        ),
    ],
    detail: Annotated[
        Any,
        Doc(
            """
                Any data to be sent to the client in the `detail` key of the JSON
                response.
                """,
        ),
    ] = None,
    headers: Annotated[
        Optional[Dict[str, str]],
        Doc(
            """
                Any headers to send to the client in the response.
                """,
        ),
    ] = None,
) -> HTTPException:
    """Log error and return an HTTP execption to be raised by the caller"""
    logger.error(detail)
    return HTTPException(status_code, detail, headers)


def read_response_error(response):
    """Read and return an HTTP response error detail."""

    # Try to read the response detail or error
    try:
        json = response.json()
        detail = json.get("detail") or json["error"]

    # If this fail, get the full response content
    except Exception:  # pylint: disable=broad-exception-caught
        detail = response.content.decode("utf-8", errors="ignore")

    return detail


def filelock(func, env_var: str):
    """
    Avoid concurrent writing to the database using a file lock.

    Args:
        env_var: environment variable that defines the folder where to save the lock file.
    """

    @functools.wraps(func)
    def with_filelock(*args, **kwargs):
        """Wrap the the call to 'func' inside the lock."""

        # Let's do this only if the RSPY_WORKING_DIR environment variable is defined.
        # Write a .lock file inside this directory.
        try:
            with FileLock(Path(os.environ[env_var]) / f"{env_var}.lock"):
                return func(*args, **kwargs)

        # Else just call the function without a lock
        except KeyError:
            return func(*args, **kwargs)

    return with_filelock


def decorate_sync_async(decorating_context, func):
    """Decorator for both sync and async functions, see: https://stackoverflow.com/a/68746329"""
    if asyncio.iscoroutinefunction(func):

        async def decorated(*args, **kwargs):
            with decorating_context(*args, **kwargs):
                return await func(*args, **kwargs)

    else:

        def decorated(*args, **kwargs):
            with decorating_context(*args, **kwargs):
                return func(*args, **kwargs)

    return functools.wraps(func)(decorated)
