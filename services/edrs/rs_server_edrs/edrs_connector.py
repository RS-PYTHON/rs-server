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

import ssl
from ftplib import FTP_TLS
from pathlib import Path
from typing import Any
from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)

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
        self.ftp: FTP_TLS | None = None
        self.disable_mlsd = disable_mlsd  # Set to True to disable MLSD command usage

    def connect(self):
        """
        Establish a secure FTPES (explicit TLS) connection.
        """
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=self.ca_cert)
        context.load_cert_chain(certfile=self.client_cert, keyfile=self.client_key)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED

        self.ftp = FTP_TLS(context=context)
        self.ftp.connect(self.host, self.port, timeout=10)
        self.ftp.auth()  # AUTH TLS (explicit)
        self.ftp.prot_p()  # Encrypt data channel
        self.ftp.login(self.login, self.password)
        logger.debug(f"Connected to {self.host}:{self.port} as {self.login}")

    def walk(self, path: str) -> list[dict[str, Any]]:
        """
        List files and directories under /NOMINAL/<path>.

        Parameters
        ----------
        path : str
            Relative path under the NOMINAL directory (e.g., "SAT123/ch_01/")

        Returns
        -------
        List[Dict[str, str | int | None]]
            List of dicts containing file/dir info with keys:
            - path: str - Full path
            - type: str - Either 'file' or 'dir'
            - size: int | None - Size in bytes for files, None for dirs

        Raises
        ------
        ConnectionError
            If not connected
        RuntimeError
            On FTP listing failure
        """
        if not self.ftp:
            raise ConnectionError("Not connected. Call connect() first.")

        base_path = f"/NOMINAL/{path.strip('/')}"

        # Try MLSD first, unless explicitly disabled
        if self.disable_mlsd:
            entries = self.ftp.nlst(base_path)
        else:
            try:
                entries = [name for name, _ in self.ftp.mlsd(base_path)]
            except Exception as e:
                logger.error(f"MLSD failed for {base_path}: {e}, using NLST instead.")
                # Fallback when MLSD is not supported
                if "500" in str(e):
                    self.disable_mlsd = True
                    entries = self.ftp.nlst(base_path)
                else:
                    raise RuntimeError(f"Failed to list {base_path} using MLSD: {e}") from e

        current_dir = self.ftp.pwd()
        results = []

        for entry in entries:
            info = {"path": entry, "type": "dir", "size": 0}

            try:
                # If cwd works, it's a directory
                self.ftp.cwd(entry)
                self.ftp.cwd(current_dir)  # Return to original dir
            except Exception:
                # If cwd fails, assume it's a file
                info["type"] = "file"
                try:
                    info["size"] = self.ftp.size(entry) or 0
                except Exception:
                    info["size"] = 0  # Some FTP servers don't support SIZE for all files

            results.append(info)

        return results

    def download(self, remote_path: str, p_local_path: str = "") -> str:
        """
        Download a file from the FTP server.

        Parameters
        ----------
        remote_path : str
            Remote path to the file (absolute or relative to current cwd).
        local_path : str, optional
            Local filesystem path to save the file. If omitted, the remote filename
            is used in the current working directory.

        Returns
        -------
        str
            The local file path where the file was saved.

        Raises
        ------
        ConnectionError
            If not connected.
        RuntimeError
            On failure to retrieve the file.
        """
        if not self.ftp:
            raise ConnectionError("Not connected. Call connect() first.")

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

    def close(self):
        """
        Close the FTP connection.
        """
        if self.ftp:
            self.ftp.quit()
            print("Connection closed.")
