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

"""Unit tests for utils module."""

import os

import pytest
from fastapi import HTTPException
from rs_server_catalog.data_management.s3_manager import S3Manager, logger
from rs_server_catalog.data_management.stac_manager import StacManager
from rs_server_catalog.utils import (
    get_temp_bucket_name,
    is_s3_path,
    verify_existing_item_from_catalog,
)
from rs_server_common.utils.pytest import pytest_common_tests
from rs_server_common.utils.utils2 import S3Credentials


class TestVerifyExistingItemFromCatalog:
    """Class to group the test cases for verify_existing_item_from_catalog function"""

    def test_post_existing_item_raises_conflict(self):
        """Test that a POST request with an existing item raises an HTTP 409 Conflict."""
        with pytest.raises(HTTPException) as excinfo:
            verify_existing_item_from_catalog(
                method="POST",
                item={"id": "existing_item"},
                content_id_str="existing_item",
                user_collection_str="user_collection",
            )
        assert excinfo.value.status_code == 409
        assert "The item existing_item already exists" in str(excinfo.value.detail)

    def test_post_nonexistent_item_no_error(self):
        """Test that a POST request with a non-existent item does not raise an error."""
        try:
            verify_existing_item_from_catalog(
                method="POST",
                item=None,
                content_id_str="new_item",
                user_collection_str="user_collection",
            )
        except HTTPException:
            pytest.fail("HTTPException should not have been raised for non-existent item with POST.")

    def test_put_nonexistent_item_raises_bad_request(self):
        """Test that a PUT request with a non-existent item raises an HTTP 400 Bad Request."""
        with pytest.raises(HTTPException) as excinfo:
            verify_existing_item_from_catalog(
                method="PUT",
                item=None,
                content_id_str="missing_item",
                user_collection_str="user_collection",
            )
        assert excinfo.value.status_code == 400
        assert "The item missing_item does not exist" in str(excinfo.value.detail)

    def test_patch_nonexistent_item_raises_bad_request(self):
        """Test that a PATCH request with a non-existent item raises an HTTP 400 Bad Request."""
        with pytest.raises(HTTPException) as excinfo:
            verify_existing_item_from_catalog(
                method="PATCH",
                item=None,
                content_id_str="missing_item",
                user_collection_str="user_collection",
            )
        assert excinfo.value.status_code == 400
        assert "The item missing_item does not exist" in str(excinfo.value.detail)

    def test_put_existing_item_no_error(self):
        """Test that a PUT request with an existing item does not raise an error."""
        try:
            verify_existing_item_from_catalog(
                method="PUT",
                item={"id": "existing_item"},
                content_id_str="existing_item",
                user_collection_str="user_collection",
            )
        except HTTPException:
            pytest.fail("HTTPException should not have been raised for existing item with PUT.")

    def test_patch_existing_item_no_error(self):
        """Test that a PATCH request with an existing item does not raise an error."""
        try:
            verify_existing_item_from_catalog(
                method="PATCH",
                item={"id": "existing_item"},
                content_id_str="existing_item",
                user_collection_str="user_collection",
            )
        except HTTPException:
            pytest.fail("HTTPException should not have been raised for existing item with PATCH.")


class TestGetS3FilenameFromAsset:
    """Class to group the test cases for verify_existing_item_from_catalog function"""

    def test_retrieve_s3_key_from_alternate_field(self):
        """Test retrieving the S3 key from the 'alternate.s3.href' field."""
        asset = {
            "href": "s3://test_catalog_bucket/path/to/filename",
            "alternate": {"https": {"href": "https://rs-server/test_catalog/path/to/filename"}},
        }
        s3_filename, alternate_field = StacManager.get_s3_filename_from_asset(asset)
        assert s3_filename == "s3://test_catalog_bucket/path/to/filename"
        assert alternate_field is True

    def test_retrieve_s3_key_from_href_field(self):
        """Test retrieving the S3 key from the 'href' field when 'alternate' is missing."""
        asset = {"href": "s3://temp_catalog/path/to/filename"}
        s3_filename, alternate_field = StacManager.get_s3_filename_from_asset(asset)
        assert s3_filename == "s3://temp_catalog/path/to/filename"
        assert alternate_field is False

    def test_missing_s3_key_raises_exception(self):
        """Test that missing 'href' and 'alternate' fields raise an HTTP 400 error."""
        with pytest.raises(HTTPException) as excinfo:
            StacManager.get_s3_filename_from_asset({})
        assert excinfo.value.status_code == 400
        assert "Failed to load the S3 key from the asset content" in str(excinfo.value.detail)

    def test_invalid_s3_key_format_raises_exception(self):
        """Test that an invalid S3 key format in 'href' raises an HTTP 400 error."""
        asset = {"href": "invalid_s3_path"}
        with pytest.raises(HTTPException) as excinfo:
            StacManager.get_s3_filename_from_asset(asset)
        assert excinfo.value.status_code == 400
        assert "Failed to load the S3 key from the asset content" in str(excinfo.value.detail)

    def test_empty_s3_key_in_href_field_raises_exception(self):
        """Test that an empty 'href' field raises an HTTP 400 error."""
        asset = {"href": ""}
        with pytest.raises(HTTPException) as excinfo:
            StacManager.get_s3_filename_from_asset(asset)
        assert excinfo.value.status_code == 400
        assert "Failed to load the S3 key from the asset content" in str(excinfo.value.detail)


class TestIsS3Path:
    """Class to group the test cases for is_s3_path function"""

    def test_is_s3_path_valid_key(self):
        """Test a valid S3 path."""
        assert is_s3_path("s3://my-bucket/my-object") is True

    def test_is_s3_path_valid_key_with_special_chars(self):
        """Test a valid S3 path with special characters."""
        assert is_s3_path("s3://my-bucket/my-object_123") is True
        assert is_s3_path("s3://my-bucket/my.object") is True
        assert is_s3_path("s3://my-bucket/my-object/with/slashes") is True

    def test_is_s3_path_invalid_key_no_bucket(self):
        """Test an invalid S3 path with no bucket."""
        assert is_s3_path("s3:///my-object") is False

    def test_is_s3_path_invalid_key_no_object(self):
        """Test an invalid S3 path with no object."""
        assert is_s3_path("s3://my-bucket/") is False

    def test_is_s3_path_invalid_key_no_scheme(self):
        """Test a path that does not start with 's3://'."""
        assert is_s3_path("my-bucket/my-object") is False

    def test_is_s3_path_invalid_key_with_spaces(self):
        """Test an invalid S3 path with spaces."""
        assert is_s3_path("s3://my-bucket/my object") is False

    def test_is_s3_path_invalid_key_non_string(self):
        """Test a non-string input."""
        assert is_s3_path(12345) is False
        assert is_s3_path(None) is False
        assert is_s3_path([]) is False
        assert is_s3_path({}) is False

    def test_is_s3_path_invalid_characters(self):
        """Test an invalid S3 path with invalid characters."""
        assert is_s3_path("s3://my-bucket/my-object$%") is False
        assert is_s3_path("s3://my-bucket/invalid#object") is False


class TestGetTempBucketName:
    """Class to group the test cases for get_temp_bucket_name function"""

    def test_get_temp_bucket_name_single_bucket(self):
        """Test with a single valid S3 bucket."""
        files_s3_key = ["s3://my-temp-bucket/file1", "s3://my-temp-bucket/file2"]
        assert get_temp_bucket_name(files_s3_key) == "my-temp-bucket"

    def test_get_temp_bucket_name_multiple_buckets(self):
        """Test with multiple buckets, expecting an exception."""
        files_s3_key = ["s3://bucket1/file1", "s3://bucket2/file2"]
        with pytest.raises(RuntimeError, match="A single temporary S3 bucket should be used"):
            get_temp_bucket_name(files_s3_key)

    def test_get_temp_bucket_name_invalid_s3_key(self):
        """Test with an invalid S3 key, expecting an exception."""
        files_s3_key = ["s3://my-temp-bucket/file1", "invalid_s3_key"]
        with pytest.raises(RuntimeError, match="does not match the correct S3 path pattern"):
            get_temp_bucket_name(files_s3_key)

    def test_get_temp_bucket_name_empty_list(self):
        """Test with an empty list, expecting None."""
        assert get_temp_bucket_name([]) is None


class TestGetS3Handler:
    """Class to group the test cases for get_s3_handler function"""

    def test_s3_handler_successful_creation(self, mocker):
        """Test successful creation of the s3_handler with valid environment variables."""
        # Mock S3StorageHandler and its delete_key_from_s3 method
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "https://fake_endpoint",
                "S3_REGION": "fake_region",
            },
        )

        mock_s3_handler = mocker.patch("rs_server_catalog.data_management.s3_manager.S3StorageHandler")
        s3_handler = S3Manager(
            S3Credentials(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            ),
        ).s3_handler

        # Assertions
        assert s3_handler is not None
        mock_s3_handler.assert_called_once_with(
            S3Credentials(
                "fake_access_key",
                "fake_secret_key",
                "https://fake_endpoint",
                "fake_region",
            ),
        )

    def test_s3_handler_creation_runtime_error(self, mocker):
        """Test that a RuntimeError during s3_handler creation returns None and prints an error."""
        # Spy calls to logger.warning(...)
        spy_log_warning = mocker.spy(logger, "warning")

        # Mock environment variables
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "https://fake_endpoint",
                "S3_REGION": "fake_region",
            },
        )

        # Mock S3StorageHandler to raise RuntimeError
        mock_s3_handler = mocker.patch(
            "rs_server_catalog.data_management.s3_manager.S3StorageHandler",
            side_effect=RuntimeError,
        )

        # Call the function and capture output
        s3_handler = S3Manager(
            S3Credentials(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],
            ),
        ).s3_handler

        # Check logger called
        spy_log_warning.assert_called_once()
        logged_message = spy_log_warning.call_args[0][0]

        # Assertions
        assert s3_handler is None
        assert "Failed to create the s3 handler" in str(logged_message)
        mock_s3_handler.assert_called_once()

    def test_check_if_item_can_be_published_success(self, mocker, s3_manager):
        """
        Test that an item with multiple assets and valid S3 keys can be published successfully.

        This test mocks the `check_s3_key` method of S3Manager to simulate that all assets
        exist in S3, and ensures that `check_if_item_can_be_published` returns True.

        - Sets `is_catalog_local_mode` to False to force real S3 checks.
        - Provides a content dictionary with two assets.
        - Mocks `check_s3_key` to return (True, size) for each asset.
        """
        # Mock a content with 2 assets and valid S3 paths
        content = {
            "collection": "test_collection",
            "properties": {"owner": "test_user"},
            "assets": {
                "asset1": {"href": "s3://rspython-ops-catalog-all-production/file1"},
                "asset2": {"href": "s3://rspython-ops-catalog-all-production/file2"},
            },
        }

        s3_manager.is_catalog_local_mode = False
        # Mock the check_s3_key method to return (True, size) for both assets
        mocker.patch.object(
            s3_manager,
            "check_s3_key",
            side_effect=[(True, 1), (True, 2)],
        )
        # Make sure that item can be published successfully
        assert s3_manager.check_if_item_can_be_published(content) is True

    def test_check_if_item_can_be_published_href_failure(self, s3_manager):
        """
        Test that an item with assets having invalid or empty S3 hrefs cannot be published.

        - Sets `is_catalog_local_mode` to False to enforce S3 checks.
        - Provides a content dictionary where all asset 'href' fields are empty.
        - Ensures that `check_if_item_can_be_published` returns False,
        indicating the item cannot be published.
        """
        # Mock a content with 2 assets with invalid hrefs
        content = {
            "collection": "test_collection",
            "properties": {"owner": "test_user"},
            "assets": {
                "asset1": {"href": ""},
                "asset2": {"href": ""},
            },
        }

        s3_manager.is_catalog_local_mode = False
        # Make sure that item can't be published successfully
        assert s3_manager.check_if_item_can_be_published(content) is False

    def test_check_if_item_can_be_published_bucket_failure(self, s3_manager):
        """
        Test that an item with assets stored in disallowed S3 buckets cannot be published.

        - Sets `is_catalog_local_mode` to False to enforce S3 bucket validation.
        - Provides a content dictionary where all asset 'href' fields point to non-allowed buckets.
        - Ensures that `check_if_item_can_be_published` returns False,
        indicating the item cannot be published due to invalid bucket paths.
        """
        # Mock a content with 2 assets with not allowed href paths
        content = {
            "collection": "test_collection",
            "properties": {"owner": "test_user"},
            "assets": {
                "asset1": {"href": "s3://not-allowed-bucket/file1"},
                "asset2": {"href": "s3://not-allowed-bucket/file2"},
            },
        }

        s3_manager.is_catalog_local_mode = False
        # Make sure that item can't be published
        assert s3_manager.check_if_item_can_be_published(content) is False

    def test_check_if_item_can_be_published_item_not_found_on_bucket(self, mocker, s3_manager):
        """
        Test that an item cannot be published if at least one asset is not found on S3.

        - Sets `is_catalog_local_mode` to False to enforce S3 checks.
        - Provides a content dictionary with multiple assets.
        - Mocks `check_s3_key` so that one asset is missing (exists=False) and the other exists.
        - Ensures that `check_if_item_can_be_published` returns False,
        reflecting that the item cannot be published if any asset is missing on the bucket.
        """
        # Mock a content with 2 assets and valid S3 paths
        content = {
            "collection": "test_collection",
            "properties": {"owner": "test_user"},
            "assets": {
                "asset1": {"href": "s3://rspython-ops-catalog-all-production/file1"},
                "asset2": {"href": "s3://rspython-ops-catalog-all-production/file2"},
            },
        }

        s3_manager.is_catalog_local_mode = False
        # Mock the check_s3_key method to return False for one asset, meaning not found on bucket.
        mocker.patch.object(
            s3_manager,
            "check_s3_key",
            side_effect=[(False, -1), (True, 2)],
        )
        # Make sure that item can't be published
        assert s3_manager.check_if_item_can_be_published(content) is False

    def test_check_if_item_can_be_published_exception(self, mocker, s3_manager):
        """
        Test that an item cannot be published if `check_s3_key` raises an HTTP exception.

        - Sets `is_catalog_local_mode` to False to enforce S3 checks.
        - Provides a content dictionary with multiple assets.
        - Mocks `check_s3_key` to raise an HTTPException for all assets.
        - Ensures that `check_if_item_can_be_published` returns False,
        reflecting that the item cannot be published when S3 checks fail due to exceptions.
        """
        # Mock a content with 2 assets and valid S3 paths
        content = {
            "collection": "test_collection",
            "properties": {"owner": "test_user"},
            "assets": {
                "asset1": {"href": "s3://rspython-ops-catalog-all-production/file1"},
                "asset2": {"href": "s3://rspython-ops-catalog-all-production/file2"},
            },
        }

        s3_manager.is_catalog_local_mode = False
        # Mock the check_s3_key method to return a http exception.
        mocker.patch.object(
            s3_manager,
            "check_s3_key",
            side_effect=HTTPException(status_code=500, detail="Unexpected error"),
        )
        # Make sure that item can't be published
        assert s3_manager.check_if_item_can_be_published(content) is False

    def test_update_assets_checksums(self, mocker, s3_manager):
        """
        Test that S3 object checksum attributes are added to each STAC asset.
        """
        content = {
            "collection": "test_collection",
            "properties": {"owner": "test_user"},
            "assets": {
                "asset1": {"href": "s3://rspython-ops-catalog-all-production/file1"},
                "asset2": {"href": "s3://rspython-ops-catalog-all-production/file2"},
            },
        }

        s3_manager.is_catalog_local_mode = False
        mocker.patch.object(
            s3_manager.s3_handler,
            "get_object_attributes",
            side_effect=[
                {"Checksum": {"ChecksumSHA256": "checksum-1"}},
                {"Checksum": {"ChecksumCRC32": "checksum-2"}},
            ],
        )

        result = s3_manager.update_assets_checksums(content)

        assert result["assets"]["asset1"]["file:checksum"] == "checksum-1"
        assert result["assets"]["asset2"]["file:checksum"] == "checksum-2"
        assert s3_manager.s3_handler.get_object_attributes.call_args_list == [
            mocker.call("rspython-ops-catalog-all-production", "file1"),
            mocker.call("rspython-ops-catalog-all-production", "file2"),
        ]


def test_middleware_order(client):
    """Check that the FastAPI application middlewares were inserted in the right order."""
    pytest_common_tests.test_middleware_order(client, use_auth_middleware=True)


def test_handle_exceptions_middleware(client, mocker):
    """Test that HandleExceptionsMiddleware handles and logs errors as expected."""
    mocker.patch("rs_server_catalog.middleware.catalog_middleware.reroute_url")
    pytest_common_tests.test_handle_exceptions_middleware(client, mocker)
