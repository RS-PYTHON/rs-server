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
Unit tests for FTPClient class.
Covers initialization, connection (FTP/FTPS), directory listing, file download,
file reading, and connection closure.
All external dependencies are mocked to avoid real network or file operations.
"""

import ssl
from ftplib import FTP, FTP_TLS  # nosec B402 # NOSONAR
from pathlib import Path

import pytest
from rs_server_common.ftp_handler.ftp_handler import FTPClient

# pylint: disable=redefined-outer-name, no-member


@pytest.fixture
def ftp_client_direct(monkeypatch):
    """
    Provide a default FTPClient instance in direct parameter mode.
    SSL is disabled by default via environment variable override.
    """
    monkeypatch.setenv("USE_SSL", "FALSE")
    client = FTPClient(
        host="localhost",
        port=21,
        user="user",
        password="pass",  # nosec B106 # NOSONAR
        ca_crt="ca.pem",
        client_crt="client.pem",
        client_key="client.key",
        use_ssl=False,
    )
    return client


def test_init_station_mode(monkeypatch):
    """Test FTPClient initialization using station environment variables."""
    monkeypatch.setenv("TEST_HOST", "127.0.0.1")
    monkeypatch.setenv("TEST_USER", "user1")
    monkeypatch.setenv("TEST_PASS", "pass1")
    monkeypatch.setenv("TEST_PORT", "2121")
    monkeypatch.setenv("USE_SSL", "true")
    monkeypatch.setenv("TEST_CA_CRT", "ca.pem")
    monkeypatch.setenv("TEST_CLIENT_CRT", "client.pem")
    monkeypatch.setenv("TEST_CLIENT_KEY", "client.key")

    client = FTPClient(station="test")

    assert client.host == "127.0.0.1"
    assert client.port == 2121
    assert client.user == "user1"
    assert client.password == "pass1"  # nosec B106 B105 # NOSONAR
    assert client.use_ssl is True
    assert client.ca_cert == "ca.pem"
    assert client.client_cert == "client.pem"
    assert client.client_key == "client.key"


def test_init_direct_missing_args():
    """Test that direct mode raises ValueError if host/user/password missing."""
    with pytest.raises(ValueError):
        FTPClient(host=None, user="user", password="pass")  # nosec B106 # NOSONAR
    with pytest.raises(ValueError):
        FTPClient(host="h", user=None, password="pass")  # nosec B106 # NOSONAR
    with pytest.raises(ValueError):
        FTPClient(host="h", user="u", password=None)


def test_connect_plain_ftp(mocker):
    """
    Test FTPClient.connect() for plain FTP (no SSL).
    Ensures:
      - FTP() object is created
      - connect() is called with correct host, port, timeout
      - login() is called with correct user/password
    """
    mock_ftp = mocker.Mock(spec=FTP)
    mocker.patch("rs_server_common.ftp_handler.ftp_handler.FTP", return_value=mock_ftp)

    client = FTPClient(host="localhost", port=21, user="user", password="pass", use_ssl=False)  # nosec B106 # NOSONAR
    client.connect()

    mock_ftp.connect.assert_called_once_with(host="localhost", port=21, timeout=10)
    mock_ftp.login.assert_called_once_with(user="user", passwd="pass")  # nosec B106 # NOSONAR
    assert client.ftp == mock_ftp


def test_connect_ftps(mocker):
    """
    Test FTPClient.connect() for FTPES (explicit TLS).
    Ensures:
      - FTP_TLS() object is created with SSL context
      - load_cert_chain() is called if client_cert and client_key are provided
      - auth(), prot_p(), login() are called in correct order
    """
    # Spy on SSL context creation
    spy_context = mocker.Mock()
    mocker.patch("ssl.create_default_context", return_value=spy_context)

    # Mock FTP_TLS object
    mock_ftp_tls = mocker.Mock(spec=FTP_TLS)
    mocker.patch("rs_server_common.ftp_handler.ftp_handler.FTP_TLS", return_value=mock_ftp_tls)

    client = FTPClient(
        host="localhost",
        port=21,
        user="user",
        password="pass",  # nosec B106 # NOSONAR
        ca_crt="ca.pem",
        client_crt="client.pem",
        client_key="key.pem",
        use_ssl=True,
    )
    client.connect()

    # SSL context methods called correctly
    ssl.create_default_context.assert_called_once_with(ssl.Purpose.SERVER_AUTH, cafile="ca.pem")  # type: ignore
    spy_context.load_cert_chain.assert_called_once_with(certfile="client.pem", keyfile="key.pem")
    assert spy_context.verify_mode == ssl.CERT_REQUIRED
    assert spy_context.check_hostname is False

    # FTP_TLS methods called correctly
    mock_ftp_tls.connect.assert_called_once_with(host="localhost", port=21, timeout=10)
    mock_ftp_tls.auth.assert_called_once()
    mock_ftp_tls.prot_p.assert_called_once()
    mock_ftp_tls.login.assert_called_once_with(user="user", passwd="pass")  # nosec B106 # NOSONAR
    assert client.ftp == mock_ftp_tls


def test_walk_nlst(mocker, ftp_client_direct):
    """Test walk() using NLST fallback when MLSD is disabled."""
    mock_ftp = mocker.Mock()
    mock_ftp.nlst.return_value = ["file1.txt", "dir1"]
    mock_ftp.pwd.return_value = "/current"

    def cwd_side_effect(arg):
        if arg == "file1.txt":
            raise OSError("not a dir")

    mock_ftp.cwd.side_effect = cwd_side_effect
    mock_ftp.size.return_value = 123

    ftp_client_direct.ftp = mock_ftp
    ftp_client_direct.disable_mlsd = True

    result = ftp_client_direct.walk("test_path")
    assert any(e["type"] == "file" for e in result)
    assert any(e["type"] == "dir" for e in result)
    assert all("path" in e and "size" in e for e in result)


def test_download_success(tmp_path, mocker, ftp_client_direct):
    """Test that download() writes file content to disk correctly."""
    mock_ftp = mocker.Mock()
    mock_ftp.retrbinary.side_effect = lambda cmd, cb: cb(b"data123")
    ftp_client_direct.ftp = mock_ftp

    local_file = tmp_path / "file.txt"
    result_path = ftp_client_direct.download("remote.txt", str(local_file))
    assert Path(result_path).exists()
    assert local_file.read_bytes() == b"data123"


def test_download_failure(tmp_path, mocker, ftp_client_direct):
    """Test that download() aborts and removes partial file on exception."""
    mock_ftp = mocker.Mock()
    mock_ftp.retrbinary.side_effect = OSError("fail")
    ftp_client_direct.ftp = mock_ftp

    local_file = tmp_path / "bad.txt"
    with pytest.raises(RuntimeError):
        ftp_client_direct.download("remote_bad.txt", str(local_file))
    assert not local_file.exists()


def test_read_file_xml(mocker, ftp_client_direct):
    """Test read_file() parses XML content into dict."""
    mock_ftp = mocker.Mock()
    xml_bytes = b"<root><a>1</a></root>"
    mock_ftp.retrbinary.side_effect = lambda cmd, cb: cb(xml_bytes)
    ftp_client_direct.ftp = mock_ftp

    result = ftp_client_direct.read_file("file.xml")
    assert isinstance(result, dict)
    assert result["root"]["a"] == "1"


def test_read_file_non_xml(mocker, ftp_client_direct):
    """Test read_file() returns raw bytes for non-XML files."""
    mock_ftp = mocker.Mock()
    mock_ftp.retrbinary.side_effect = lambda cmd, cb: cb(b"binarydata")
    ftp_client_direct.ftp = mock_ftp

    result = ftp_client_direct.read_file("file.bin")
    assert result == b"binarydata"


def test_close_calls_quit(mocker, ftp_client_direct):
    """Test close() calls quit() on the FTP object."""
    mock_ftp = mocker.Mock()
    ftp_client_direct.ftp = mock_ftp

    ftp_client_direct.close()
    mock_ftp.quit.assert_called_once()
    assert ftp_client_direct.ftp is None


def test_close_quit_exception_calls_close(mocker, ftp_client_direct):
    """Test close() fallback to close() if quit() raises an exception."""
    mock_ftp = mocker.Mock()
    mock_ftp.quit.side_effect = OSError("fail quit")
    ftp_client_direct.ftp = mock_ftp

    ftp_client_direct.close()
    mock_ftp.close.assert_called_once()
    assert ftp_client_direct.ftp is None
