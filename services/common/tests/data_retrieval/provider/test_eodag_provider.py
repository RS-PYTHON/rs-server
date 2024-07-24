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

"""Unit tests for EodagProvider."""

import json
import os
import tempfile
from pathlib import Path
from threading import Thread
from typing import Any, List

import pytest
import responses
from eodag import EODataAccessGateway
from rs_server_common.data_retrieval.eodag_provider import EodagProvider
from rs_server_common.data_retrieval.provider import CreateProviderFailed, Provider


def mock_cadip_download(product_id: str, with_content: dict | None = None):
    """Mock cadip download request using responses.

    :param product_id: the id of the downloaded product
    :param with_content: content of the file downloaded (default content is used otherwise)
    :return: the mocked Response object
    """
    # TODO verify that mock is compliant with CADIP ICD
    default_content = {
        "key 1": "content 1",
        "info 2": "value 2",
    }
    response = responses.Response(
        responses.GET,
        f"http://127.0.0.1:5000/Files({product_id})/$value",
        json=with_content or default_content,
        status=200,
    )
    responses.add(response)
    return response


class TestAEodagProvider:
    """Class used to test the functionality of the EodagProvider class."""

    def test_is_a_provider(self, cadip_config):
        """
        Verifies that EodagProvider is an instance of the Provider class.

        This test checks if an instance of EodagProvider is also an instance of the Provider class.

        """
        provider = EodagProvider(cadip_config.file, cadip_config.provider)
        assert isinstance(provider, Provider)

    def test_is_initialised_with_the_given_config(self, cadip_config):
        """
        Verifies that EodagProvider is initialized with the given configuration.

        This test checks if an instance of EodagProvider is properly initialized with the
        provided configuration, including the creation of an EODataAccessGateway client.

        """
        # ensure that EODAG_CFG_DIR env var does not exist
        del os.environ["EODAG_CFG_DIR"]
        provider = EodagProvider(cadip_config.file, cadip_config.provider)
        # check that EODAG_CFG_DIR env var has been set
        assert "EODAG_CFG_DIR" in os.environ
        # check the value of EODAG_CFG_DIR
        assert os.getenv("EODAG_CFG_DIR") == provider.eodag_cfg_dir.name
        # check the existence of the temp directory
        assert os.path.isdir(provider.eodag_cfg_dir.name)
        assert isinstance(provider.client, EODataAccessGateway)
        # check that EODAG_CFG_DIR env var was set
        assert cadip_config.provider in provider.client.available_providers()
        # test if the temp path is deleted
        # directly calling the destructor, keep in mind that this one is not
        # guaranteed to be called by python itself
        provider.__del__()  # pylint: disable=unnecessary-dunder-call
        assert not os.path.isdir(provider.eodag_cfg_dir.name)

    def test_cant_be_initialized_with_a_wrong_configuration(self, not_found_config):
        """
        Verifies that EodagProvider raises CreateProviderFailed exception with a wrong configuration.

        This test checks if EodagProvider raises a CreateProviderFailed exception when attempting to
        initialize with a wrong configuration, and if the exception message and cause match expectations.

        """
        with pytest.raises(CreateProviderFailed) as exc_info:
            EodagProvider(not_found_config.file, not_found_config.provider)
        assert "Can't initialize WRONG provider" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, FileNotFoundError)


# TODO A EodagProvider search ...


class TestAEodagProviderDownload:
    """Class used to test the download functionality of the EodagProvider class."""

    @responses.activate
    @pytest.mark.xfail
    def test_authent_on_the_remote_data_source_using_its_config(self):
        """
        Tests the authentication on the remote data source using its configuration.

        This test checks the authentication process on the remote data source, utilizing the
        configuration provided to the EodagProvider. It is currently marked as expected to fail (xfail).

        """
        # FIXME configure authent on eodag (currently dummy)
        assert False

    @responses.activate
    @pytest.mark.xfail
    def test_fails_if_the_authentication_fails(self):
        """
        Tests the case where authentication fails on the remote data source.

        This test checks how EodagProvider behaves when the authentication on the remote data source fails.
        It is currently marked as expected to fail (xfail).

        """
        # FIXME configure authent on eodag (currently dummy)
        # TODO check how the cadip server reacts in case of authent error
        assert False

    @responses.activate
    def test_download_the_file_on_the_remote_data_source_using_its_config(self, cadip_config, tmp_path):
        """
        Tests the download of a file on the remote data source using its configuration.

        This test checks if EodagProvider can successfully download a file from the remote data source
        using its provided configuration. It also verifies that the expected request is made.

        """
        product_id = "1"

        # The mock enables to assert the expected request is used:
        # base URL and usage of the product ID
        download_response = mock_cadip_download(product_id)

        provider = EodagProvider(cadip_config.file, cadip_config.provider)
        downloaded_file = tmp_path / "downloaded.txt"
        provider.download(product_id, downloaded_file)

        assert download_response.call_count == 1

    @responses.activate
    @pytest.mark.xfail
    def test_fails_if_the_download_fails(self):
        """
        Tests the case where the download from the remote data source fails.

        This test identifies the error cases from the CADIP server and verifies each one of them.
        It is currently marked as expected to fail (xfail).

        """
        # TODO identify the error cases from CADIP server and verify each one of them
        assert False

    @responses.activate
    def test_write_the_downloaded_file_at_the_given_location(self, cadip_config, tmp_path):
        """
        Tests writing the downloaded file at the given location.

        This test checks if EodagProvider can successfully write the downloaded file at the specified location,
        using the content mocked from the CADIP server response.

        """
        product_id = "1"

        content = {
            "key 1": "content 1",
            "info 2": "value 2",
        }
        mock_cadip_download(product_id, content)

        provider = EodagProvider(cadip_config.file, cadip_config.provider)
        downloaded_file = tmp_path / "downloaded.txt"
        provider.download(product_id, downloaded_file)
        downloaded_file = downloaded_file / "downloaded.txt"  # eodag 3.0 specific
        assert downloaded_file.exists()
        assert downloaded_file.is_file()

        with open(downloaded_file, encoding="utf-8") as f:
            actual_content = json.load(f)
        assert actual_content == content

    @responses.activate
    def test_parallel_download_at_the_given_location(self, cadip_config):
        """
        Tests writing the downloaded file at the given location.

        This test checks if EodagProvider can successfully write the downloaded file at the specified location,
        using the content mocked from the CADIP server response.

        """

        def dwn_thread(cc, idx, result):
            product_id = f"file_{idx}.tmp"

            content = {
                f"thread_{idx}": f"content {idx}",
                f"info {idx}": f"value {idx}",
            }
            mock_cadip_download(product_id, content)

            provider = EodagProvider(cc.file, cc.provider)
            with tempfile.TemporaryDirectory() as download_dir:
                downloaded_file = Path(download_dir) / f"downloaded_thread_{idx}.txt"
                provider.download(product_id, downloaded_file)
                downloaded_file = downloaded_file / f"downloaded_thread_{idx}.txt"  # Eodag 3.0 specific
                assert downloaded_file.exists()
                assert downloaded_file.is_file()

                with open(downloaded_file, encoding="utf-8") as f:
                    actual_content = json.load(f)

                assert actual_content == content
            result[idx] = provider.eodag_cfg_dir
            # directly calling the destructor, keep in mind that this one is not
            # guaranteed to be called by python itself
            provider.__del__()  # pylint: disable=unnecessary-dunder-call

        request_threads: List[Thread] = []
        nb_of_threads = 10
        results: Any = [None] * nb_of_threads
        for idx in range(nb_of_threads):
            request_threads.append(Thread(target=dwn_thread, args=(cadip_config, idx, results)))
        for dt in request_threads:
            dt.start()
        for dt in request_threads:
            dt.join()
        # assure that the temp dirs created by eodag are unique
        assert len(results) == len(set(results))
        # check if all the temp dirs have been deleted (by directly calling the destructor in the thread)
        for res in results:
            assert isinstance(res, tempfile.TemporaryDirectory)
            assert not os.path.isdir(res.name)
