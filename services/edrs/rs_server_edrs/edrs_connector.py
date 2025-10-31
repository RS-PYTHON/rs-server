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


import ssl
from ftplib import FTP_TLS
from typing import List, Dict


class EDRSConnector:
    def __init__(self, host: str, port: int, login: str, password: str,
                 ca_cert: str, client_cert: str, client_key: str):
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
        self.ftp = None

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
        self.ftp.auth()   # AUTH TLS (explicit)
        self.ftp.prot_p() # Encrypt data channel
        self.ftp.login(self.login, self.password)
        print(f"Connected to {self.host}:{self.port} as {self.login}")

    # ============================================================
    # LIST version (simple, returns raw directory listing strings)
    # ============================================================
    def list_satellite_files_list(self, satellite_id: str) -> List[str]:
        """
        List all files under NOMINAL/<satellite_id>/ch_<x>/ using LIST.
        Returns a flat list of raw strings.
        """
        if not self.ftp:
            raise ConnectionError("Not connected. Call connect() first.")

        base_dir = f"/NOMINAL/{satellite_id}"
        self.ftp.cwd(base_dir)
        channels = [d for d in self.ftp.nlst() if d.startswith("ch_")]

        all_entries = []
        for ch in channels:
            path = f"{base_dir}/{ch}"
            print(f"Listing (LIST): {path}")
            self.ftp.cwd(path)
            raw_entries = []
            self.ftp.retrlines("LIST", raw_entries.append)
            for line in raw_entries:
                all_entries.append(f"{path}: {line}")

        return all_entries

    # ============================================================
    # MLSD version (structured, RFC 3659)
    # ============================================================
    def list_satellite_files_mlsd(self, satellite_id: str) -> List[Dict[str, str]]:
        """
        List all files under NOMINAL/<satellite_id>/ch_<x>/ using MLSD.
        Returns structured facts (RFC 3659): type, size, modify, perm, etc.
        """
        if not self.ftp:
            raise ConnectionError("Not connected. Call connect() first.")

        base_dir = f"/NOMINAL/{satellite_id}"
        self.ftp.cwd(base_dir)
        channels = [d for d in self.ftp.nlst() if d.startswith("ch_")]

        all_facts = []
        for ch in channels:
            path = f"{base_dir}/{ch}"
            print(f"Listing (MLSD): {path}")
            self.ftp.cwd(path)
            try:
                for name, facts in self.ftp.mlsd():
                    facts["name"] = name
                    facts["path"] = f"{path}/{name}"
                    all_facts.append(facts)
            except Exception as e:
                print(f"MLSD not supported for {path}: {e}")

        return all_facts

    def close(self):
        """
        Close the FTP connection.
        """
        if self.ftp:
            self.ftp.quit()
            print("Connection closed.")
