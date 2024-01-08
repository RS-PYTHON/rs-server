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
    def test_is_a_provider(self, cadip_config):
        provider = EodagProvider(cadip_config)
        assert isinstance(provider, Provider)

    def test_is_initialised_with_the_given_config(self, cadip_config):
        provider = EodagProvider(cadip_config)
        assert isinstance(provider.client, EODataAccessGateway)
        assert cadip_config.provider in provider.client.available_providers()

    def test_cant_be_initialized_with_a_wrong_configuration(self, not_found_config):
        with pytest.raises(CreateProviderFailed) as exc_info:
            EodagProvider(not_found_config)
        assert "Can't initialize WRONG provider" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, FileNotFoundError)


# TODO A EodagProvider search ...


class TestAEodagProviderDownload:
    @responses.activate
    @pytest.mark.xfail
    def test_authent_on_the_remote_data_source_using_its_config(self):
        # FIXME configure authent on eodag (currently dummy)
        assert False

    @responses.activate
    @pytest.mark.xfail
    def test_fails_if_the_authentication_fails(self):
        # FIXME configure authent on eodag (currently dummy)
        # TODO check how the cadip server reacts in case of authent error
        assert False

    @responses.activate
    def test_download_the_file_on_the_remote_data_source_using_its_config(self, cadip_config, tmp_path):
        product_id = "1"

        # The mock enables to assert the expected request is used :
        # base url and usage of the product id
        download_response = mock_cadip_download(product_id)

        provider = EodagProvider(cadip_config)
        downloaded_file = tmp_path / "downloaded.txt"
        provider.download(product_id, downloaded_file)

        assert download_response.call_count == 1

    @responses.activate
    @pytest.mark.xfail
    def test_fails_if_the_download_fails(self):
        # TODO identify the error cases from CADIP server and verify each one of them
        assert False

    @responses.activate
    def test_write_the_downloaded_file_at_the_given_location(self, cadip_config, tmp_path):
        product_id = "1"

        content = {
            "key 1": "content 1",
            "info 2": "value 2",
        }
        mock_cadip_download(product_id, content)

        provider = EodagProvider(cadip_config)
        downloaded_file = tmp_path / "downloaded.txt"
        provider.download(product_id, downloaded_file)

        assert downloaded_file.exists()
        assert downloaded_file.is_file()

        with open(downloaded_file, encoding="utf-8") as f:
            actual_content = json.load(f)
        assert actual_content == content
