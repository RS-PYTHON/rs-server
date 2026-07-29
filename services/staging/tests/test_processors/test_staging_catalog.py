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
# pylint: disable=too-many-lines

"""Test module for Staging processor with catalog."""

import httpx
import pytest
import requests
from pygeoapi.util import JobStatus
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_staging.processors.processor_staging import Staging
from rs_server_staging.utils.rspy_models import Feature, FeatureCollectionModel

# pylint: disable=no-member


class TestStagingCatalog:
    """Group of all tests used for method that search the catalog before processing."""

    def _call_check_catalog(self, staging_instance: Staging, staging_inputs: dict):
        return staging_instance.check_catalog(
            staging_inputs["collection"],
            FeatureCollectionModel.model_validate(staging_inputs["items"]["value"]).features,
        )

    @pytest.mark.asyncio
    async def test_check_catalog_success(self, mocker, staging_instance: Staging, staging_inputs: dict):
        """Test the check_catalog method for successful execution.

        This test verifies that the check_catalog method correctly formats the request
        to the catalog URL and handles the response appropriately.

        Args:
            mocker: The mocker fixture to patch methods and objects during tests.
            staging_instance (Staging): An instance of the Staging class, pre-initialized for testing.
            staging_inputs: pytest fixture providing the staging input data (collection and features).
        """
        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        # mock all other called methods
        mock_create_streaming_list = mocker.patch.object(staging_instance, "create_streaming_list", return_value=None)

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"type": "FeatureCollection", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mocker.patch("rs_server_common.settings.http_client", return_value=httpx.AsyncClient())
        mocked_get = mocker.patch("httpx.AsyncClient.get", return_value=mock_response)
        mocker.patch.object(staging_instance, "check_if_collection_exists", return_value=True)
        # Call the method under test
        result = await self._call_check_catalog(staging_instance, staging_inputs)

        # Assert that the result is True (successful catalog check)
        assert result is True

        # Construct the expected filter string
        expected_filter_object = {
            "collections": "test_collection",
            "filter-lang": "cql2-text",
            "filter": "id IN ('1','2')",
            "limit": "2",
        }
        # Assert that requests.get was called with the correct parameters
        mocked_get.assert_called_once_with(  # type: ignore
            f"{staging_instance.catalog_url}/catalog/search",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
            params=expected_filter_object,
            timeout=5,
        )
        mock_create_streaming_list.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_catalog_get_wrong_response(self, mocker, staging_instance: Staging, staging_inputs: dict):
        """docstring to be added"""
        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"wrong_key": "Unknown_test", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mocker.patch("requests.get", return_value=mock_response)

        # Call the method under test
        result = await self._call_check_catalog(staging_instance, staging_inputs)

        # Assert that the result is True (successful catalog check)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_catalog_failure(self, mocker, staging_instance: Staging, staging_inputs: dict):
        """docstring to be added"""
        # Setting up the catalog_url and headers
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        # Loop trough all possible exception raised during request.get and check if failure happen
        for possible_exception in [
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
        ]:
            # mock all other called methods
            mock_log_job_execution = mocker.patch.object(staging_instance, "log_job_execution", return_value=None)

            get_err_msg = "HTTP Error msg"
            mocker.patch("requests.get", side_effect=possible_exception(get_err_msg))

            # Mock the create_streaming_list method
            mock_create_streaming_list = mocker.patch.object(staging_instance, "create_streaming_list")

            # Call the method under test
            result = await self._call_check_catalog(staging_instance, staging_inputs)

            # Assert that the result is False (failed catalog check)
            assert result is False

            # Assert that create_streaming_list was not called during failure
            mock_create_streaming_list.assert_not_called()
            mock_log_job_execution.assert_called_once_with(
                JobStatus.failed,
                0,
                f"Failed to create catalog collection: {get_err_msg}",
            )

        # Mock the requests.get method
        mock_response = mocker.Mock()
        mock_response.json.return_value = {"type": "FeatureCollection", "features": []}  # Mocking the JSON response
        mock_response.raise_for_status = mocker.Mock()  # Mock raise_for_status to do nothing
        mock_log_job_execution = mocker.patch.object(staging_instance, "log_job_execution", return_value=None)
        mocker.patch("rs_server_common.settings.http_client", return_value=httpx.AsyncClient())
        mocker.patch("httpx.AsyncClient.get", return_value=mock_response)
        err_msg = "RE test msg"
        mocker.patch.object(
            staging_instance,
            "create_streaming_list",
            side_effect=RuntimeError(err_msg),
        )
        # Mock that collection exists
        mocker.patch.object(
            staging_instance,
            "check_if_collection_exists",
            return_value=True,
        )
        # Call the method under test
        await self._call_check_catalog(staging_instance, staging_inputs)
        mock_log_job_execution.assert_called_once_with(
            JobStatus.failed,
            0,
            f"Failed to search catalog: {err_msg}",
        )

    @pytest.mark.asyncio
    async def test_check_catalog_collection_not_exists(self, mocker, staging_instance: Staging, staging_inputs: dict):
        """Cover the branch where the catalog collection does NOT exist."""

        # Force the collection to be missing
        mocker.patch(
            "asyncio.to_thread",
            new=mocker.AsyncMock(return_value=False),
        )

        mocker.patch("requests.get")  # not called
        mocker.patch.object(staging_instance, "create_streaming_list")  # not called

        result = await self._call_check_catalog(staging_instance, staging_inputs)
        assert result is False

    @pytest.mark.asyncio
    async def test_check_catalog_keeps_input_assets_for_expired_items(
        self,
        mocker,
        staging_instance: Staging,
        staging_inputs: dict,
    ):
        """Expired catalog items (unpublished flag set) should keep input assets for restaging."""
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        mock_response = mocker.Mock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "1",
                    "assets": {},
                    "properties": {"unpublished": "2026-01-01T00:00:00.000000Z"},
                },
            ],
        }
        mock_response.raise_for_status = mocker.Mock()
        mocker.patch("rs_server_common.settings.http_client", return_value=httpx.AsyncClient())
        mocker.patch("httpx.AsyncClient.get", return_value=mock_response)
        mocker.patch.object(staging_instance, "check_if_collection_exists", return_value=True)

        result = await self._call_check_catalog(staging_instance, staging_inputs)

        assert result is True
        assert [feature.id for feature in staging_instance.expired_items] == ["1"]
        assert "asset1" in staging_instance.expired_items[0].assets
        assert sorted(feature.id for feature in staging_instance.stream_list) == ["1", "2"]

    @pytest.mark.asyncio
    async def test_check_catalog_restages_items_with_empty_assets_no_unpublished(
        self,
        mocker,
        staging_instance: Staging,
        staging_inputs: dict,
    ):
        """Items whose assets were wiped by DataLifecycle (empty dict, no unpublished) must be restaged.

        The DataLifecycle can clear the assets dict without immediately setting 'unpublished'.
        In that state the item must still be detected as needing re-staging.
        """
        staging_instance.catalog_url = "https://test_rspy_catalog_url.com"

        # Feature "1" -> empty assets, no 'unpublished' property -> must be restaged via PUT
        # Feature "2" -> not present in the catalog at all -> must be staged fresh via POST
        mock_response = mocker.Mock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "1",
                    "assets": {},
                    "properties": {},  # no 'unpublished' field
                },
            ],
        }
        mock_response.raise_for_status = mocker.Mock()
        mocker.patch("rs_server_common.settings.http_client", return_value=httpx.AsyncClient())
        mocker.patch("httpx.AsyncClient.get", return_value=mock_response)
        mocker.patch.object(staging_instance, "check_if_collection_exists", return_value=True)

        result = await self._call_check_catalog(staging_instance, staging_inputs)

        assert result is True
        # Feature "1" must be marked as expired (will be updated via PUT)
        assert [feature.id for feature in staging_instance.expired_items] == ["1"]
        # Input assets must be preserved on the expired feature for re-downloading
        assert "asset1" in staging_instance.expired_items[0].assets
        # Both features end up in the stream list: "2" as a new item, "1" as an expired one
        assert sorted(feature.id for feature in staging_instance.stream_list) == ["1", "2"]


class TestStagingPublishCatalog:
    """Class to group tests for catalog publishing after streaming was processes"""

    def test_publish_rspy_feature_success(self, mocker, staging_instance: Staging):
        """Test successful feature publishing to the catalog."""
        feature = mocker.Mock()  # Mock the feature object
        feature.model_dump_json.return_value = (
            '{"id": "feature1", "properties": {"name": "test"}}'  # Mock the JSON serialization
        )
        feature.assets = {}

        # Mock requests.post to return a successful response
        mock_response = mocker.Mock()
        mock_response.raise_for_status.return_value = None  # No error
        mock_post = mocker.patch("requests.post", return_value=mock_response)

        result = staging_instance.publish_rspy_feature("test_collection", feature)

        assert result is True  # Should return True for successful publishing
        mock_post.assert_called_once_with(
            f"{staging_instance.catalog_url}/catalog/collections/test_collection/items",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key", "Content-Type": "application/geo+json"},
            data=feature.model_dump_json(),
            timeout=staging_instance.catalog_publish_timeout,
        )
        feature.model_dump_json.assert_called()  # Ensure the feature JSON serialization was called

    def test_publish_rspy_feature_fail(self, mocker, staging_instance: Staging):
        """Test failure during feature publishing and cleanup on error."""
        feature = mocker.Mock()
        feature.model_dump_json.return_value = '{"id": "feature1", "properties": {"name": "test"}}'
        feature.assets = {}

        for possible_exception in [
            requests.exceptions.HTTPError,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
        ]:
            # Mock requests.post to raise an exception
            mock_post = mocker.patch("requests.post", side_effect=possible_exception("HTTP Error occurred"))

            # Mock the logger and other methods called on failure
            mock_logger = mocker.patch.object(staging_instance, "logger")

            result = staging_instance.publish_rspy_feature("test_collection", feature)

            assert result is False  # Should return False for failure
            mock_post.assert_called_once_with(
                f"{staging_instance.catalog_url}/catalog/collections/test_collection/items",
                headers={
                    "cookie": "fake-cookie",
                    APIKEY_HEADER: "fake-api-key",
                    "Content-Type": "application/geo+json",
                },
                data=feature.model_dump_json(),
                timeout=staging_instance.catalog_publish_timeout,
            )
            mock_logger.error.assert_called_once_with(
                "Error while publishing items in rspy catalog HTTP Error occurred",
            )

    def test_publish_rspy_feature_timeout_retry_success(self, mocker, staging_instance: Staging):
        """Test that a timeout is retried before succeeding."""
        feature = mocker.Mock()
        feature.model_dump_json.return_value = '{"id": "feature1", "properties": {"name": "test"}}'
        feature.assets = {}

        mock_response = mocker.Mock()
        mock_response.raise_for_status.return_value = None
        mock_post = mocker.patch(
            "requests.post",
            side_effect=[requests.exceptions.Timeout("timeout"), mock_response],
        )
        mock_sleep = mocker.patch("time.sleep")
        mock_logger = mocker.patch.object(staging_instance, "logger")

        result = staging_instance.publish_rspy_feature("test_collection", feature)

        assert result is True
        assert mock_post.call_count == 2
        mock_sleep.assert_called_once_with(staging_instance.catalog_publish_retry_delay)
        mock_logger.warning.assert_called_once_with(
            f"Timeout while publishing items in rspy catalog. "
            f"Retry 1/{staging_instance.catalog_publish_max_retries} in "
            f"{staging_instance.catalog_publish_retry_delay}s",
        )
        mock_logger.error.assert_not_called()

    def test_publish_rspy_feature_timeout_retry_exhausted(self, mocker, staging_instance: Staging):
        """Test that staging gives up after the configured number of timeout retries."""
        feature = mocker.Mock()
        feature.model_dump_json.return_value = '{"id": "feature1", "properties": {"name": "test"}}'
        feature.assets = {}

        timeout_error = requests.exceptions.Timeout("HTTP Error occurred")
        mock_post = mocker.patch("requests.post", side_effect=timeout_error)
        mock_sleep = mocker.patch("time.sleep")
        mock_logger = mocker.patch.object(staging_instance, "logger")

        result = staging_instance.publish_rspy_feature("test_collection", feature)

        assert result is False
        assert mock_post.call_count == staging_instance.catalog_publish_max_retries + 1
        assert mock_sleep.call_count == staging_instance.catalog_publish_max_retries
        mock_logger.error.assert_called_once_with("Error while publishing items in rspy catalog HTTP Error occurred")

    def test_update_expired_rspy_feature_success(self, mocker, staging_instance: Staging):
        """Test successful update of an expired feature already present in the catalog."""
        feature = Feature(
            type="Feature",
            properties={"unpublished": "2026-01-01T00:00:00.000000Z"},
            id="feature1",
            stac_version="1.1.0",
            assets={"asset1": {"href": "s3://bucket/path"}},
            stac_extensions=[],
        )
        feature.assets["asset1"].alternate = {"s3": {"href": "s3://alternate/path"}}  # type: ignore[attr-defined]

        mock_response = mocker.Mock()
        mock_response.raise_for_status.return_value = None
        mock_put = mocker.patch("requests.put", return_value=mock_response)

        result = staging_instance.update_expired_rspy_feature("test_collection", feature)

        assert result is True
        assert feature.properties["unpublished"] == "2026-01-01T00:00:00.000000Z"
        assert not hasattr(feature.assets["asset1"], "alternate")
        mock_put.assert_called_once_with(
            f"{staging_instance.catalog_url}/catalog/collections/test_collection/items/feature1",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key", "Content-Type": "application/geo+json"},
            data=feature.model_dump_json(),
            timeout=staging_instance.catalog_publish_timeout,
        )

    def test_publish_processed_features_updates_expired_items(self, mocker, staging_instance: Staging):
        """Expired items should use PUT update flow, while new items keep POST publish flow."""
        expired_feature = Feature(
            type="Feature",
            properties={},
            id="expired-feature",
            stac_version="1.1.0",
            assets={"asset1": {"href": "s3://bucket/expired"}},
            stac_extensions=[],
        )
        new_feature = Feature(
            type="Feature",
            properties={},
            id="new-feature",
            stac_version="1.1.0",
            assets={"asset1": {"href": "s3://bucket/new"}},
            stac_extensions=[],
        )
        staging_instance.stream_list = [expired_feature, new_feature]
        staging_instance.expired_items = [expired_feature]

        mock_update = mocker.patch.object(staging_instance, "update_expired_rspy_feature", return_value=True)
        mock_publish = mocker.patch.object(staging_instance, "publish_rspy_feature", return_value=True)

        result = staging_instance.publish_processed_features("test_collection", {})

        assert result is True
        mock_update.assert_called_once_with("test_collection", expired_feature)
        mock_publish.assert_called_once_with("test_collection", new_feature)

    def test_repr(self, staging_instance: Staging):
        """Test repr method for coverage"""
        assert repr(staging_instance) == "RSPY Staging OGC API Processor"


class TestStagingUnpublishCatalog:
    """Class to group tests for catalog unpublishing after streaming failed"""

    def test_unpublish_rspy_features_success(self, mocker, staging_instance: Staging):
        """Test successful unpublishing feature ids to the catalog."""
        feature_ids = ["feature-1", "feature-2"]
        mock_logger = mocker.patch.object(staging_instance, "logger")

        # Mock requests.delete to return a successful response

        mock_delete = mocker.patch("requests.delete")
        mock_delete.return_value.status_code = 200

        staging_instance.unpublish_rspy_features("test_collection", feature_ids)

        # Assert that delete was called with the correct URL and headers
        mock_delete.assert_any_call(
            f"{staging_instance.catalog_url}/catalog/collections/test_collection/items/feature-1",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
            timeout=3,
        )
        mock_delete.assert_any_call(
            f"{staging_instance.catalog_url}/catalog/collections/test_collection/items/feature-2",
            headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
            timeout=3,
        )
        # Ensure no error was logged
        mock_logger.error.assert_not_called()

    def test_unpublish_rspy_features_fail(self, mocker, staging_instance: Staging):
        """Test failure during feature unpublishing ."""
        feature_ids = ["feature-1"]

        for possible_exception in [
            requests.exceptions.HTTPError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
            requests.exceptions.ConnectionError,
        ]:
            # Mock requests.post to raise an exception
            mock_delete = mocker.patch("requests.delete", side_effect=possible_exception("HTTP Error occurred"))

            # Mock the logger and other methods called on failure
            mock_logger = mocker.patch.object(staging_instance, "logger")

            staging_instance.unpublish_rspy_features("test_collection", feature_ids)

            mock_delete.assert_any_call(
                f"{staging_instance.catalog_url}/catalog/collections/test_collection/items/feature-1",
                headers={"cookie": "fake-cookie", APIKEY_HEADER: "fake-api-key"},
                timeout=3,
            )
            mock_logger.error.assert_called_once_with("Error while deleting the item from rspy catalog %s", mocker.ANY)

    def test_repr(self, staging_instance: Staging):
        """Test repr method for coverage"""
        assert repr(staging_instance) == "RSPY Staging OGC API Processor"
