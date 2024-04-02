"""Unit tests for EodagProvider."""

import json

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
        provider = EodagProvider(cadip_config.file, cadip_config.provider)
        assert isinstance(provider.client, EODataAccessGateway)
        assert cadip_config.provider in provider.client.available_providers()

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

        assert downloaded_file.exists()
        assert downloaded_file.is_file()

        with open(downloaded_file, encoding="utf-8") as f:
            actual_content = json.load(f)
        assert actual_content == content
