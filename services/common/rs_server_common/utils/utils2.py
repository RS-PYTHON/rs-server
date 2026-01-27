# Copyright 2023-2025 Airbus, CS Group
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
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.concurrency import iterate_in_threadpool
from fastapi.responses import StreamingResponse
from filelock import FileLock


@dataclass
class AuthInfo:
    """User authentication information in KeyCloak."""

    # User login (preferred username)
    user_login: str

    # IAM roles
    iam_roles: list[str]

    # Oauth2 attributes and/or custom `config` associated to the API key
    attributes: dict[str, Any]


def read_response_error(response):
    """Read and return an HTTP response error detail."""

    # Try to read the response detail or error
    try:
        _json = response.json()
        detail = _json.get("detail") or _json.get("description") or _json["error"]

    # If this fail, get the full response content
    except Exception:  # pylint: disable=broad-exception-caught
        detail = response.content.decode("utf-8", errors="ignore")

    return detail


async def read_streaming_response(response: StreamingResponse) -> Any | None:
    """Read a json-formatted streaming response content"""
    try:
        body = [chunk async for chunk in response.body_iterator]
        splits = map(lambda x: x if isinstance(x, bytes) else x.encode(), body)  # type: ignore[union-attr]
        str_content = b"".join(splits).decode()
        py_content = json.loads(str_content) if str_content else None

        return py_content

    # Reset the StreamingResponse so it can be used again
    finally:
        response.body_iterator = iterate_in_threadpool(iter(body))


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
