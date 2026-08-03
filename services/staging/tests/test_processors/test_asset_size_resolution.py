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

"""Tests for resolving the byte size of staging source assets."""

import botocore
import pytest
import requests
from rs_server_common.authentication.token_auth import TokenAuth
from rs_server_staging.processors.processor_staging import Staging
from rs_server_staging.utils.asset_info import AssetInfo


class TestAssetSizeResolution:
    """Test source asset size validation and provider metadata resolution."""

    @pytest.mark.parametrize(
        ("content_length", "expected"),
        [
            (0, 0),
            (42, 42),
            ("123", 123),
        ],
    )
    def test_coerce_content_length_valid(self, content_length, expected):
        """Accept integer and numeric-string content lengths, including zero."""
        asset = AssetInfo("https://provider.example/product.bin", "product.bin", "destination")

        assert Staging.coerce_content_length(content_length, asset) == expected

    @pytest.mark.parametrize(
        ("content_length", "error_message"),
        [
            (None, "Missing Content-Length"),
            (True, "Invalid Content-Length"),
            ("not-a-number", "Invalid Content-Length"),
            ([], "Invalid Content-Length"),
            (-1, "Invalid negative Content-Length"),
        ],
    )
    def test_coerce_content_length_invalid(self, content_length, error_message):
        """Reject missing, boolean, non-numeric, and negative content lengths."""
        asset = AssetInfo("https://provider.example/product.bin", "product.bin", "destination")

        with pytest.raises(RuntimeError, match=error_message) as exc_info:
            Staging.coerce_content_length(content_length, asset)

        assert asset.product_url in str(exc_info.value)

    @pytest.mark.parametrize("use_refresh_token", [False, True], ids=["without-token", "with-token"])
    def test_resolve_http_asset_size(self, mocker, staging_instance: Staging, use_refresh_token):
        """Read Content-Length using HEAD and optional provider authentication."""
        asset = AssetInfo("https://provider.example/product.bin", "product.bin", "destination")
        response = mocker.Mock()
        response.headers = {"Content-Length": "2048"}
        head_mock = mocker.patch(
            "rs_server_staging.processors.processor_staging.requests.head",
            return_value=response,
        )
        refresh_tokens = {}
        if use_refresh_token:
            refresh_token = mocker.Mock()
            refresh_token.get_access_token.return_value = "access-token"
            refresh_tokens[asset.domain] = refresh_token

        result = staging_instance.resolve_http_asset_size(asset, refresh_tokens)

        assert result == 2048
        response.raise_for_status.assert_called_once_with()
        head_mock.assert_called_once_with(
            asset.product_url,
            auth=mocker.ANY,
            allow_redirects=True,
            timeout=60,
        )
        auth = head_mock.call_args.kwargs["auth"]
        if use_refresh_token:
            assert isinstance(auth, TokenAuth)
            assert auth.token == "access-token"
            refresh_token.get_access_token.assert_called_once_with()
        else:
            assert auth is None

    def test_resolve_http_asset_size_request_failure(self, mocker, staging_instance: Staging):
        """Wrap provider request failures with source asset context."""
        asset = AssetInfo("https://provider.example/product.bin", "product.bin", "destination")
        request_error = requests.exceptions.RequestException("provider unavailable")
        mocker.patch(
            "rs_server_staging.processors.processor_staging.requests.head",
            side_effect=request_error,
        )

        with pytest.raises(RuntimeError, match="Failed to retrieve Content-Length") as exc_info:
            staging_instance.resolve_http_asset_size(asset, {})

        assert asset.product_url in str(exc_info.value)
        assert exc_info.value.__cause__ is request_error

    @pytest.mark.parametrize(
        "product_url",
        ["s3:///product.bin", "s3://source-bucket"],
        ids=["missing-bucket", "missing-key"],
    )
    def test_resolve_s3_asset_size_rejects_invalid_url(self, staging_instance: Staging, product_url):
        """Require both a source bucket and an object key."""
        asset = AssetInfo(product_url, "product.bin", "destination", origin_service="s3")

        with pytest.raises(RuntimeError, match="Invalid S3 source URL") as exc_info:
            staging_instance.resolve_s3_asset_size(asset)

        assert product_url in str(exc_info.value)

    def test_resolve_s3_asset_size(self, mocker, staging_instance: Staging):
        """Read ContentLength from HeadObject using the source S3 configuration."""
        asset = AssetInfo(
            "s3://source-bucket/nested/product.bin",
            "product.bin",
            "destination",
            origin_service="s3",
            external_s3_endpoint_url="https://s3.example",
            external_s3_access_key="access-key",
            external_s3_secret_key="secret-key",  # nosec B106
        )
        source_s3_client = mocker.Mock()
        source_s3_client.head_object.return_value = {"ContentLength": 4096}
        client_mock = mocker.patch(
            "rs_server_staging.processors.processor_staging.boto3.client",
            return_value=source_s3_client,
        )

        result = staging_instance.resolve_s3_asset_size(asset)

        assert result == 4096
        client_mock.assert_called_once_with(
            "s3",
            endpoint_url="https://s3.example",
            aws_access_key_id="access-key",
            aws_secret_access_key="secret-key",  # nosec B106
            use_ssl=True,
        )
        source_s3_client.head_object.assert_called_once_with(
            Bucket="source-bucket",
            Key="nested/product.bin",
        )

    def test_resolve_s3_asset_size_head_failure(self, mocker, staging_instance: Staging):
        """Wrap HeadObject failures with source asset context."""
        asset = AssetInfo("s3://source-bucket/product.bin", "product.bin", "destination", origin_service="s3")
        client_error = botocore.exceptions.ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}},
            "HeadObject",
        )
        source_s3_client = mocker.Mock()
        source_s3_client.head_object.side_effect = client_error
        mocker.patch(
            "rs_server_staging.processors.processor_staging.boto3.client",
            return_value=source_s3_client,
        )

        with pytest.raises(RuntimeError, match="Failed to retrieve ContentLength") as exc_info:
            staging_instance.resolve_s3_asset_size(asset)

        assert asset.product_url in str(exc_info.value)
        assert exc_info.value.__cause__ is client_error

    @pytest.mark.parametrize(
        ("product_url", "origin_service", "resolver_name"),
        [
            ("https://provider.example/product.bin", "s3", "resolve_s3_asset_size"),
            ("s3://source-bucket/product.bin", "http", "resolve_s3_asset_size"),
            ("http://provider.example/product.bin", "http", "resolve_http_asset_size"),
            ("https://provider.example/product.bin", "http", "resolve_http_asset_size"),
        ],
        ids=["s3-service", "s3-scheme", "http", "https"],
    )
    def test_resolve_asset_sizes_dispatches_by_source(
        self,
        mocker,
        staging_instance: Staging,
        product_url,
        origin_service,
        resolver_name,
    ):
        """Use the metadata operation supported by each source protocol."""
        asset = AssetInfo(product_url, "product.bin", "destination", origin_service=origin_service)
        staging_instance.assets_info = [asset]
        refresh_tokens = {"provider.example": mocker.Mock()}
        s3_resolver = mocker.patch.object(staging_instance, "resolve_s3_asset_size", return_value=8192)
        http_resolver = mocker.patch.object(staging_instance, "resolve_http_asset_size", return_value=8192)
        logger = mocker.patch.object(staging_instance, "logger")

        staging_instance.resolve_asset_sizes(refresh_tokens)

        assert asset.size_bytes == 8192
        if resolver_name == "resolve_s3_asset_size":
            s3_resolver.assert_called_once_with(asset)
            http_resolver.assert_not_called()
        else:
            http_resolver.assert_called_once_with(asset, refresh_tokens)
            s3_resolver.assert_not_called()
        logger.info.assert_called_once_with(
            "Resolved size for source asset %s: %s bytes",
            product_url,
            8192,
        )

    def test_resolve_asset_sizes_rejects_unsupported_source(self, mocker, staging_instance: Staging):
        """Fail when neither STAC metadata nor a supported metadata operation is available."""
        asset = AssetInfo("ftp://provider.example/product.bin", "product.bin", "destination")
        staging_instance.assets_info = [asset]
        s3_resolver = mocker.patch.object(staging_instance, "resolve_s3_asset_size")
        http_resolver = mocker.patch.object(staging_instance, "resolve_http_asset_size")

        with pytest.raises(RuntimeError) as exc_info:
            staging_instance.resolve_asset_sizes({})

        assert str(exc_info.value) == (
            "Cannot determine the size of source asset 'ftp://provider.example/product.bin': "
            "unsupported scheme 'ftp' and no STAC file:size was provided."
        )
        s3_resolver.assert_not_called()
        http_resolver.assert_not_called()

    @pytest.mark.parametrize("known_size", [0, 1024], ids=["zero", "positive"])
    def test_resolve_asset_sizes_keeps_stac_size(self, mocker, staging_instance: Staging, known_size):
        """Keep valid STAC file:size metadata without querying the provider."""
        asset = AssetInfo(
            "https://provider.example/product.bin",
            "product.bin",
            "destination",
            size_bytes=known_size,
        )
        staging_instance.assets_info = [asset]
        s3_resolver = mocker.patch.object(staging_instance, "resolve_s3_asset_size")
        http_resolver = mocker.patch.object(staging_instance, "resolve_http_asset_size")

        staging_instance.resolve_asset_sizes({})

        assert asset.size_bytes == known_size
        s3_resolver.assert_not_called()
        http_resolver.assert_not_called()
