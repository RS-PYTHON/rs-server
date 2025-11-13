# Copyright 2025 CS Group
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

"""EDRS Connector module for secure FTPES communication."""

import io
import os
import ssl
from ftplib import FTP, FTP_TLS  # nosec B402
from pathlib import Path
from typing import Any

import xmltodict
from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)

NOT_CONNECTED_ERROR_MSG = "Not connected. Call connect() first."


class EDRSConnector:
    """EDRS Connector using FTPES (FTP over explicit TLS) for secure file transfers."""

    def __init__(
        self,
        host: str,
        port: int,
        login: str,
        password: str,
        ca_cert: str,
        client_cert: str,
        client_key: str,
        disable_mlsd=True,
    ):
        """
        Initialize EDRS connector with FTPS (FTPES) credentials.
        """
        self.host = host
        self.port = port
        self.login = login
        self.password = password
        self.ca_cert = ca_cert
        self.client_cert = client_cert
        self.client_key = client_key
        self.ftp: FTP | FTP_TLS | None = None
        self.disable_mlsd = disable_mlsd  # Set to True to disable MLSD command usage
        # Read environment variable (defaults to FALSE)
        use_ssl_env = os.getenv("USE_SSL", "FALSE").strip().lower()
        self.use_ssl = use_ssl_env in ["1", "true", "yes"]

    def connect(self):
        """
        Establish an FTP or FTPES (explicit TLS) connection depending on USE_SSL.
        """
        if self.use_ssl:
            logger.debug("Connecting via FTPES (explicit TLS)...")
            # EDRS uses internal certificates; hostname verification intentionally disabled.
            context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=self.ca_cert)  # NOSONAR
            if self.client_cert and self.client_key:
                context.load_cert_chain(certfile=self.client_cert, keyfile=self.client_key)
            context.check_hostname = False  # NOSONAR
            context.verify_mode = ssl.CERT_REQUIRED

            self.ftp = FTP_TLS(context=context)
            self.ftp.connect(self.host, self.port, timeout=10)
            self.ftp.auth()  # AUTH TLS (explicit)
            self.ftp.prot_p()  # Encrypt data channel
            self.ftp.login(self.login, self.password)
        else:
            logger.debug("Connecting via plain FTP (no SSL)...")
            self.ftp = FTP()  # nosec B321 # NOSONAR
            self.ftp.connect(self.host, self.port, timeout=10)
            self.ftp.login(self.login, self.password)

        logger.info(f"Connected to {self.host}:{self.port} as {self.login}")

    def walk(self, path: str) -> list[dict[str, Any]]:
        """List files and directories under /NOMINAL/<path>.

        Args:
            path (str): Relative path under the NOMINAL directory
                (e.g., "SAT123/ch_01/").

        Returns:
            list[dict[str, str | int | None]]: A list of dictionaries containing
                information about each file or directory.

        Raises:
            ConnectionError: If the FTP client is not connected.
            RuntimeError: If the FTP listing operation fails.
        """

        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)

        base_path = f"/NOMINAL/{path.strip('/')}"

        entries = self._list_directory_entries(base_path)

        current_dir = self.ftp.pwd()
        results = []

        for entry in entries:
            info = self._get_entry_info(entry, current_dir)
            results.append(info)

        return results

    def _list_directory_entries(self, base_path: str) -> list[str]:
        """Helper to list directory entries, handling MLSD/NLST fallback."""
        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)
        if self.disable_mlsd:
            return self.ftp.nlst(base_path)

        try:
            return [name for name, _ in self.ftp.mlsd(base_path)]
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"MLSD failed for {base_path}: {e}, using NLST instead.")
            if "500" in str(e):
                self.disable_mlsd = True
                return self.ftp.nlst(base_path)
            raise RuntimeError(f"Failed to list {base_path} using MLSD: {e}") from e

    def _get_entry_info(self, entry: str, current_dir: str) -> dict[str, Any]:
        """Helper to determine type and size of an FTP entry."""
        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)
        info = {"path": entry, "type": "dir", "size": 0}
        try:
            self.ftp.cwd(entry)
            self.ftp.cwd(current_dir)
            return info
        except Exception:  # pylint: disable=broad-except
            info["type"] = "file"
            try:
                info["size"] = self.ftp.size(entry) or 0
            except Exception:  # pylint: disable=broad-except
                info["size"] = 0
            return info

    def download(self, remote_path: str, p_local_path: str = "") -> str:
        """Download a file from the FTP server.

        Args:
            remote_path (str): Remote path to the file (absolute or relative to the current working directory).
            local_path (str, optional): Local filesystem path where the file will be saved.
                If omitted, the remote filename is used in the current working directory.

        Returns:
            str: The local file path where the file was saved.

        Raises:
            ConnectionError: If the FTP client is not connected.
            RuntimeError: If the file cannot be retrieved.
        """

        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)

        # Determine local target path
        local_path: Path = Path(p_local_path) if p_local_path else Path(Path(remote_path).name)
        if not local_path.name:
            raise ValueError("remote_path has no filename and no local_path provided")

        # Ensure directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with local_path.open("wb") as f:
                self.ftp.retrbinary(f"RETR {remote_path}", f.write)
        except Exception as e:
            local_path.unlink(missing_ok=True)  # Remove partial file if exists
            raise RuntimeError(f"Failed to download {remote_path}: {e}") from e

        return str(local_path)

    def read_file(self, remote_path: str) -> Any:
        """
        Read a file from the FTP server directly into memory.

        If the file is XML, it is parsed into a Python dictionary.
        Otherwise, the raw bytes content is returned.

        Args:
            remote_path (str): Path to the file on the FTP server.

        Returns:
            dict | bytes: A dictionary if the file is XML, otherwise raw bytes.

        Raises:
            ConnectionError: If the FTP client is not connected.
            RuntimeError: If the file cannot be retrieved or parsed.
        """

        if not self.ftp:
            raise ConnectionError(NOT_CONNECTED_ERROR_MSG)

        buffer = io.BytesIO()

        try:
            # Retrieve the remote file into memory
            self.ftp.retrbinary(f"RETR {remote_path}", buffer.write)
        except Exception as e:
            error_msg = str(e)
            if "550" in error_msg or "Not a plain file" in error_msg:
                logger.error(f"Remote path '{remote_path}' is a directory, not a file.")
                raise RuntimeError(f"Remote path '{remote_path}' appears to be a directory, not a file.") from e
            logger.error(f"Failed to read remote file '{remote_path}': {e}")
            raise RuntimeError(f"Failed to read remote file '{remote_path}': {e}") from e

        buffer.seek(0)

        # Check if file is XML based on extension
        if remote_path.lower().endswith(".xml"):
            try:
                # Parse XML into dict
                content = xmltodict.parse(buffer.getvalue())
                return content
            except Exception as e:
                raise RuntimeError(f"Failed to parse XML file {remote_path}: {e}") from e
        else:
            # Return raw bytes for non-XML files
            return buffer.getvalue()

    def close(self):
        """Close the FTP connection."""
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:  # pylint: disable=broad-except
                self.ftp.close()
            logger.info("Connection closed.")
