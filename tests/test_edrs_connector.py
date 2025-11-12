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

"""Unit tests for the EDRSConnector class."""
from pathlib import Path

import pytest

from services.edrs.rs_server_edrs.edrs_connector import EDRSConnector

# pylint: disable=redefined-outer-name


@pytest.fixture
def connector(monkeypatch):
    """Fixture providing a default EDRSConnector instance with SSL disabled."""
    monkeypatch.setenv("USE_SSL", "FALSE")

    value = "value_not_a_password"  # deliberately non-sensitive dummy string

    return EDRSConnector(
        host="test_host",
        port=21,
        login="test_user",
        password=value,
        ca_cert="ca.pem",
        client_cert="client.crt",
        client_key="client.key",
    )


def test_init_sets_correct_attributes(monkeypatch):
    """Verify that __init__ correctly sets attributes and interprets USE_SSL."""
    monkeypatch.setenv("USE_SSL", "true")

    value = "value_not_a_password"

    conn = EDRSConnector(
        "h",
        21,
        "login_test",
        value,
        "ca",
        "crt",
        "key",
    )

    assert conn.host == "h"
    assert conn.port == 21
    assert conn.login == "login_test"
    assert conn.password == value
    assert conn.ca_cert == "ca"
    assert conn.use_ssl is True


def test_connect_with_ssl(mocker, connector, monkeypatch):
    """Test that connect() establishes a secure FTPES connection with SSL enabled."""
    monkeypatch.setenv("USE_SSL", "TRUE")
    connector.use_ssl = True

    mock_ftps = mocker.Mock()
    mock_ftps.connect = mocker.Mock()
    mock_ftps.auth = mocker.Mock()
    mock_ftps.prot_p = mocker.Mock()
    mock_ftps.login = mocker.Mock()

    mock_context = mocker.Mock()
    mocker.patch("ssl.create_default_context", return_value=mock_context)

    mocker.patch("services.edrs.rs_server_edrs.edrs_connector.FTP_TLS", return_value=mock_ftps)

    connector.connect()

    mock_context.load_cert_chain.assert_called_once_with(certfile="client.crt", keyfile="client.key")
    mock_ftps.connect.assert_called_once_with("test_host", 21, timeout=10)
    mock_ftps.auth.assert_called_once()
    mock_ftps.prot_p.assert_called_once()
    mock_ftps.login.assert_called_once_with("user", "pass")
    assert connector.ftp == mock_ftps


def test_connect_without_ssl(mocker, connector):
    """Test that connect() uses plain FTP when SSL is disabled."""
    connector.use_ssl = False

    mock_ftp = mocker.Mock()
    mock_ftp.connect = mocker.Mock()
    mock_ftp.login = mocker.Mock()

    mocker.patch("services.edrs.rs_server_edrs.edrs_connector.FTP", return_value=mock_ftp)

    connector.connect()

    mock_ftp.connect.assert_called_once_with("test_host", 21, timeout=10)
    mock_ftp.login.assert_called_once_with("user", "pass")
    assert connector.ftp == mock_ftp


def test_walk_raises_if_not_connected(connector):
    """Ensure walk() raises ConnectionError when called without an active FTP connection."""
    with pytest.raises(ConnectionError):
        connector.walk("some/path")


def test_walk_with_nlst(mocker, connector):
    """Test walk() listing files using NLST when MLSD is disabled."""
    mock_ftp = mocker.Mock()
    mock_ftp.nlst.return_value = ["file1.txt", "dir1"]
    mock_ftp.pwd.return_value = "/current"
    mock_ftp.size.return_value = 123

    def mock_cwd(arg):
        if arg == "file1.txt":
            raise Exception("not a dir")  # pylint: disable=broad-exception-raised

    mock_ftp.cwd.side_effect = mock_cwd
    connector.ftp = mock_ftp

    result = connector.walk("data")

    assert len(result) == 2
    assert any(e["type"] == "file" for e in result)
    assert any(e["type"] == "dir" for e in result)


def test_walk_with_mlsd_and_fallback(mocker, connector):
    """Test that walk() falls back to NLST when MLSD is unsupported."""
    connector.disable_mlsd = False
    mock_ftp = mocker.Mock()
    mock_ftp.mlsd.side_effect = Exception("500 MLSD not supported")
    mock_ftp.nlst.return_value = ["a", "b"]
    mock_ftp.pwd.return_value = "/"
    mock_ftp.cwd.side_effect = Exception("file")
    connector.ftp = mock_ftp

    result = connector.walk("test")
    assert connector.disable_mlsd is True
    assert len(result) == 2


def test_walk_with_mlsd_runtime_error(mocker, connector):
    """Verify that walk() raises RuntimeError for MLSD failures not matching fallback conditions."""
    connector.disable_mlsd = False
    mock_ftp = mocker.Mock()
    mock_ftp.mlsd.side_effect = Exception("Something else")
    connector.ftp = mock_ftp

    with pytest.raises(RuntimeError):
        connector.walk("test")


def test_download_success(tmp_path, mocker, connector):
    """Ensure download() successfully retrieves a file and writes it to disk."""
    mock_ftp = mocker.Mock()
    connector.ftp = mock_ftp
    file_path = tmp_path / "file.txt"
    mock_ftp.retrbinary.side_effect = lambda cmd, cb: cb(b"data")

    result = connector.download("remote/file.txt", str(file_path))

    assert Path(result).exists()
    with open(result, "rb") as f:
        assert f.read() == b"data"


def test_download_failure(tmp_path, mocker, connector):
    """Test that download() raises RuntimeError and removes partial files on failure."""
    mock_ftp = mocker.Mock()
    connector.ftp = mock_ftp
    mock_ftp.retrbinary.side_effect = Exception("failure")
    local_path = tmp_path / "bad.txt"

    with pytest.raises(RuntimeError):
        connector.download("remote/bad.txt", str(local_path))

    assert not local_path.exists()


def test_download_without_connection(connector):
    """Ensure download() raises ConnectionError when no FTP connection exists."""
    with pytest.raises(ConnectionError):
        connector.download("file.txt")


def test_read_file_non_xml(mocker, connector):
    """Test read_file() returns raw bytes for non-XML files."""
    mock_ftp = mocker.Mock()
    mock_ftp.retrbinary.side_effect = lambda cmd, cb: cb(b"abc123")
    connector.ftp = mock_ftp

    result = connector.read_file("file.bin")

    assert result == b"abc123"


def test_read_file_xml(mocker, connector):
    """Test read_file() parses XML files into Python dictionaries."""
    mock_ftp = mocker.Mock()
    xml_content = b"<root><a>1</a></root>"
    mock_ftp.retrbinary.side_effect = lambda cmd, cb: cb(xml_content)
    connector.ftp = mock_ftp

    result = connector.read_file("file.xml")

    assert isinstance(result, dict)
    assert result["root"]["a"] == "1"


def test_read_file_xml_parse_error(mocker, connector):
    """Verify read_file() raises RuntimeError on invalid XML content."""
    mock_ftp = mocker.Mock()
    mock_ftp.retrbinary.side_effect = lambda cmd, cb: cb(b"<root>")
    connector.ftp = mock_ftp
    mocker.patch("xmltodict.parse", side_effect=Exception("bad xml"))

    with pytest.raises(RuntimeError):
        connector.read_file("bad.xml")


def test_read_file_error_directory(mocker, connector):
    """Ensure read_file() raises RuntimeError when the remote path is a directory."""
    mock_ftp = mocker.Mock()
    mock_ftp.retrbinary.side_effect = Exception("550 Not a plain file")
    connector.ftp = mock_ftp

    with pytest.raises(RuntimeError):
        connector.read_file("dirpath")


def test_close_success(mocker, connector):
    """Verify close() calls quit() when FTP connection exists."""
    mock_ftp = mocker.Mock()
    connector.ftp = mock_ftp

    connector.close()
    mock_ftp.quit.assert_called_once()


def test_close_with_exception(mocker, connector):
    """Test that close() calls close() as a fallback if quit() raises an exception."""
    mock_ftp = mocker.Mock()
    mock_ftp.quit.side_effect = Exception("bad")
    connector.ftp = mock_ftp

    connector.close()
    mock_ftp.close.assert_called_once()
