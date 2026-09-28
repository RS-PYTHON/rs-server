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

"""Unit tests for the main module (uvicorn launcher)."""

import sys

import pytest
from rs_server_catalog import main
from rs_server_catalog.main import UvicornSettings


class TestUvicornSettings:
    """Class to group the test cases for the UvicornSettings class"""

    def test_default_values(self, monkeypatch):
        """Test the default values, same as the ones removed from the stac-fastapi 7.0.0 ApiSettings."""
        # The conftest loads a .env file that sets these env vars, so remove them
        for env_var in ("APP_HOST", "APP_PORT", "RELOAD"):
            monkeypatch.delenv(env_var, raising=False)

        settings = UvicornSettings(_env_file=None)

        assert settings.app_host == "0.0.0.0"  # nosec B104
        assert settings.app_port == 8000
        assert settings.reload is True

    def test_values_from_env(self, monkeypatch):
        """Test that the values are read and converted from the APP_HOST, APP_PORT and RELOAD env vars."""
        monkeypatch.setenv("APP_HOST", "127.0.0.1")
        monkeypatch.setenv("APP_PORT", "8083")
        monkeypatch.setenv("RELOAD", "false")

        settings = UvicornSettings(_env_file=None)

        assert settings.app_host == "127.0.0.1"
        assert settings.app_port == 8083
        assert settings.reload is False


def test_run(mocker, monkeypatch):
    """Test that run() starts uvicorn with the UvicornSettings values."""
    monkeypatch.setattr(main, "settings", UvicornSettings(app_host="127.0.0.1", app_port=8083, reload=False))
    monkeypatch.setenv("RELOAD_DIRS", "dir1, dir2,")
    monkeypatch.setenv("UVICORN_ROOT_PATH", "/root_path")
    mock_uvicorn_run = mocker.patch("uvicorn.run")

    main.run()

    mock_uvicorn_run.assert_called_once_with(
        "rs_server_catalog.app:app",
        host="127.0.0.1",
        port=8083,
        log_level="info",
        reload=False,
        reload_dirs=["dir1", "dir2"],
        root_path="/root_path",
    )


def test_run_without_uvicorn(mocker):
    """Test that run() raises an explicit error when uvicorn is not installed."""
    mocker.patch.dict(sys.modules, {"uvicorn": None})

    with pytest.raises(RuntimeError, match="Uvicorn must be installed"):
        main.run()
