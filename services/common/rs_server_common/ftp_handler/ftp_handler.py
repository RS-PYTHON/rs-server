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
FTP/FTPS client module.
Provides a unified interface for connecting to FTP or FTPS servers,
listing directories, downloading files, reading XML content, and closing connections.
Includes detailed logging for debugging and traceability.
"""

import io
import os
import ssl
from ftplib import FTP, FTP_TLS  # nosec B402 # NOSONAR
from pathlib import Path
from typing import Any

import xmltodict
from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)

NOT_CONNECTED_ERROR_MSG = "Not connected. Call connect() first."


class FTPClient:
    """Unified FTP/FTPS client supporting both station-based and direct configuration."""

    def __init__(
        self,
        station: str | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        ca_crt: str | None = None,
        client_crt: str | None = None,
        client_key: str | None = None,
        use_ssl: bool | None = None,
        disable_mlsd: bool = True,
    ):
        """
        Initialize FTPClient from either station prefix (legacy) or direct host/user/password.

        Direct parameters override station-based lookup.

        Args:
            station: Optional station prefix to read env variables.
            host: FTP host.
            port: FTP port, default 21.
            user: FTP username.
            password: FTP password.
            ca_crt: Path to CA certificate for SSL.
            client_crt: Path to client certificate for SSL.
            client_key: Path to client key for SSL.
            use_ssl: Force SSL usage (overrides env USE_SSL).
            disable_mlsd: Disable MLSD listing.
        """
        # Station-based mode
        if station:
            prefix = station.upper()
            self.host = os.environ.get(f"{prefix}_HOST")
            self.port = int(os.environ.get(f"{prefix}_PORT", "21"))
            self.user = os.environ.get(f"{prefix}_USER")
            self.password = os.environ.get(f"{prefix}_PASS")

            if not all([self.host, self.user, self.password]):
                logger.error("Incomplete environment configuration for station: %s", station)
                raise ValueError(f"Incomplete environment configuration for station: {station}")

            self.ca_cert = os.getenv(f"{prefix}_CA_CRT")
            self.client_cert = os.getenv(f"{prefix}_CLIENT_CRT")
            self.client_key = os.getenv(f"{prefix}_CLIENT_KEY")
            self.use_ssl = os.getenv("USE_SSL", "false").strip().lower() in ("1", "true", "yes")

        # Direct parameter mode
        else:
            self.host = host
            self.port = port or 21
            self.user = user
            self.password = password
            if not all([self.host, self.user, self.password]):
                logger.error("Missing host/user/password when no station is provided")
                raise ValueError("Missing host/user/password when no station is provided")

            self.ca_cert = ca_crt
            self.client_cert = client_crt
            self.client_key = client_key
            self.use_ssl = use_ssl if use_ssl else os.getenv("USE_SSL", "false").strip().lower() in ("1", "true", "T")

        self.disable_mlsd = disable_mlsd
        self.ftp: FTP | None = None
        logger.debug("Initialized FTPClient: host=%s, use_ssl=%s", self.host, self.use_ssl)

    def connect(self) -> None:
        """Establish FTP or FTPES connection depending on USE_SSL."""

        # Validate required fields
        if self.host is None or self.user is None or self.password is None:
            raise RuntimeError("Cannot connect: host, user, or password is None")

        if self.use_ssl:
            # Create SSL context for server authentication
            context: ssl.SSLContext = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=self.ca_cert)

            # Load client certificate if provided
            if self.client_cert is not None and self.client_key is not None:
                context.load_cert_chain(certfile=self.client_cert, keyfile=self.client_key)

            context.verify_mode = ssl.CERT_REQUIRED
            context.check_hostname = False  # NOSONAR

            self.ftp = FTP_TLS(context=context)

            # Connect and login
            self.ftp.connect(host=self.host, port=self.port, timeout=10)
            self.ftp.auth()
            self.ftp.login(user=self.user, passwd=self.password)
            self.ftp.prot_p()
        else:
            self.ftp = FTP()  # nosec B321 # NOSONAR
            self.ftp.connect(host=self.host, port=self.port, timeout=10)
            self.ftp.login(user=self.user, passwd=self.password)

    def walk(self, path: str) -> list[dict[str, Any]]:
        """List directory contents at the given remote path."""
        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)
        base_path = path.rstrip("/")
        entries = self._list_directory_entries(base_path)
        current_dir = self.ftp.pwd()
        results: list[dict[str, Any]] = []

        for entry in entries:
            info = self._get_entry_info(entry, current_dir)
            results.append(info)
        return results

    def _list_directory_entries(self, base_path: str) -> list[str]:
        """List entries using MLSD or NLST depending on disable_mlsd flag."""
        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)
        if self.disable_mlsd:
            return self.ftp.nlst(base_path)

        try:
            return [name for name, _ in self.ftp.mlsd(base_path)]
        except OSError:
            logger.warning("MLSD unsupported, falling back to NLST")
            self.disable_mlsd = True
            return self.ftp.nlst(base_path)

    def _get_entry_info(self, entry: str, current_dir: str) -> dict[str, Any]:
        """Return dict with path, type, and size for a file or directory."""
        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)
        info = {"path": entry, "type": "dir", "size": 0}
        try:
            self.ftp.cwd(entry)
            self.ftp.cwd(current_dir)
        except Exception:  # pylint: disable=broad-exception-caught
            info["type"] = "file"
            try:
                info["size"] = self.ftp.size(entry) or 0
            except OSError:
                info["size"] = 0
        return info

    def download(self, remote_path: str, local_path="") -> str:
        """Download remote file to local filesystem."""
        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)
        local_path = Path(local_path) if local_path else Path(Path(remote_path).name)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with local_path.open("wb") as f:
                self.ftp.retrbinary(f"RETR {remote_path}", f.write)
            logger.info("Downloaded %s to %s", remote_path, local_path)
        except OSError as e:
            local_path.unlink(missing_ok=True)
            logger.exception("Failed to download %s", remote_path)
            raise RuntimeError(f"Failed to download {remote_path}: {e}") from e
        return str(local_path)

    def read_file(self, remote_path: str) -> Any:
        """Read remote file into memory; parse XML if extension is .xml."""
        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)
        buffer = io.BytesIO()
        try:
            self.ftp.retrbinary(f"RETR {remote_path}", buffer.write)
        except OSError as e:
            logger.exception("Failed to read remote file %s", remote_path)
            raise RuntimeError(f"Failed to read remote file '{remote_path}': {e}") from e
        buffer.seek(0)
        if remote_path.lower().endswith(".xml"):
            try:
                return xmltodict.parse(buffer.getvalue())
            except xmltodict.expat.ExpatError as e:
                logger.exception("Failed to parse XML file %s", remote_path)
                raise RuntimeError(f"Failed to parse XML file {remote_path}: {e}") from e
        return buffer.getvalue()

    def close(self):
        """Close FTP connection safely."""
        if self.ftp:
            try:
                self.ftp.quit()
                logger.info("FTP connection closed gracefully")
            except OSError:
                self.ftp.close()
                logger.warning("FTP connection forcibly closed")
            finally:
                self.ftp = None
