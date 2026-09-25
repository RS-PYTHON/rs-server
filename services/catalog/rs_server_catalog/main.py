# Copyright 2023-2026 Airbus, CS Group
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

"""RS-Server STAC catalog based on stac-fastapi-pgstac."""

import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class UvicornSettings(BaseSettings):
    """
    Uvicorn deployment settings, read from the APP_HOST, APP_PORT and RELOAD env vars.

    They were removed from the stac-fastapi ApiSettings in stac-fastapi 7.0.0, so we define them here
    with the same names and default values.
    """

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    reload: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = UvicornSettings()


def run():
    """Run app from command line using uvicorn if available."""
    try:
        import uvicorn  # pylint: disable=import-outside-toplevel

        uvicorn.run(
            "rs_server_catalog.app:app",
            host=settings.app_host,
            port=settings.app_port,
            log_level="info",
            reload=settings.reload,
            reload_dirs=[dir.strip() for dir in os.getenv("RELOAD_DIRS", "").split(",") if dir],
            # NOTE: don't set workers= use the WEB_CONCURRENCY env var instead
            root_path=os.getenv("UVICORN_ROOT_PATH", ""),
        )
    except ImportError:
        raise RuntimeError("Uvicorn must be installed in order to use command")  # pylint: disable=raise-missing-from


if __name__ == "__main__":
    run()
