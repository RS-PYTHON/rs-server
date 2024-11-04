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

"""Unit tests for utils module."""

import os

import pytest
from fastapi import HTTPException
from rs_server_catalog.utils import (
    delete_s3_files,
    get_s3_filename_from_asset,
    get_s3_handler,
    get_temp_bucket_name,
    is_s3_path,
    verify_existing_item_from_catalog,
)


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
        assert "Conflict error! The item existing_item already exists" in str(excinfo.value.detail)

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
        asset = {"alternate": {"s3": {"href": "s3://test_catalog_bucket/path/to/filename"}}}
        s3_filename, alternate_field = get_s3_filename_from_asset(asset)
        assert s3_filename == "s3://test_catalog_bucket/path/to/filename"
        assert alternate_field is True

    def test_retrieve_s3_key_from_href_field(self):
        """Test retrieving the S3 key from the 'href' field when 'alternate' is missing."""
        asset = {"href": "s3://temp_catalog/path/to/filename"}
        s3_filename, alternate_field = get_s3_filename_from_asset(asset)
        assert s3_filename == "s3://temp_catalog/path/to/filename"
        assert alternate_field is False

    def test_missing_s3_key_raises_exception(self):
        """Test that missing 'href' and 'alternate' fields raise an HTTP 400 error."""
        with pytest.raises(HTTPException) as excinfo:
            get_s3_filename_from_asset({})
        assert excinfo.value.status_code == 400
        assert "Failed to load the S3 key from the asset content" in str(excinfo.value.detail)

    def test_invalid_s3_key_format_raises_exception(self):
        """Test that an invalid S3 key format in 'href' raises an HTTP 400 error."""
        asset = {"href": "invalid_s3_path"}
        with pytest.raises(HTTPException) as excinfo:
            get_s3_filename_from_asset(asset)
        assert excinfo.value.status_code == 400
        assert "Failed to load the S3 key from the asset content" in str(excinfo.value.detail)

    def test_empty_s3_key_in_href_field_raises_exception(self):
        """Test that an empty 'href' field raises an HTTP 400 error."""
        asset = {"href": ""}
        with pytest.raises(HTTPException) as excinfo:
            get_s3_filename_from_asset(asset)
        assert excinfo.value.status_code == 400
        assert "Failed to load the S3 key from the asset content" in str(excinfo.value.detail)


class TestDeleteS3Files:
    """Class to group the test cases for delete_s3_files function"""

    def test_delete_s3_files_empty_list(self, mocker):
        """Test the behavior when the list of S3 files to be deleted is empty."""
        mock_logger = mocker.patch("rs_server_catalog.utils.logger")
        result = delete_s3_files([])

        assert result is True
        mock_logger.info.assert_called_once_with("No files to be deleted from bucket")

    def test_delete_s3_files_no_s3_handler(self, mocker):
        """Test the behavior when the S3 handler cannot be created."""
        mock_logger = mocker.patch("rs_server_catalog.utils.logger")
        mocker.patch("rs_server_catalog.utils.get_s3_handler", return_value=None)

        result = delete_s3_files(["s3://bucket_name/path/to/file"])

        assert result is False
        mock_logger.error.assert_called_once_with("Failed to create the s3 handler when trying to delete the s3 files")

    def test_delete_s3_files_valid_paths(self, mocker):
        """Test the behavior with valid S3 paths for deletion."""
        mock_logger = mocker.patch("rs_server_catalog.utils.logger")
        mock_get_s3_handler = mocker.patch("rs_server_catalog.utils.get_s3_handler")
        mocker.patch("rs_server_catalog.utils.is_s3_path", return_value=True)
        mock_s3_handler = mocker.Mock()
        mock_get_s3_handler.return_value = mock_s3_handler

        result = delete_s3_files(["s3://bucket_name/path/to/file"])

        assert result is True
        mock_s3_handler.delete_file_from_s3.assert_called_once_with("bucket_name", "path/to/file")
        mock_logger.error.assert_not_called()

    def test_delete_s3_files_invalid_s3_path(self, mocker):
        """Test the behavior when an invalid S3 path is provided."""
        mock_logger = mocker.patch("rs_server_catalog.utils.logger")
        mock_s3_handler = mocker.patch("rs_server_catalog.utils.get_s3_handler")
        mocker.patch("rs_server_catalog.utils.is_s3_path", return_value=False)

        result = delete_s3_files(["invalid_path"])

        assert result is True
        mock_s3_handler.delete_file_from_s3.assert_not_called()
        mock_logger.error.assert_called_once_with(
            "The requested s3 key invalid_path for deletion does not match the "
            "correct S3 path pattern (s3://bucket_name/path/to/obj). Skipping",
        )

    def test_delete_s3_files_deletion_runtime_error(self, mocker):
        """Test the behavior when a RuntimeError occurs during deletion."""
        mock_logger = mocker.patch("rs_server_catalog.utils.logger")
        mock_get_s3_handler = mocker.patch("rs_server_catalog.utils.get_s3_handler")
        mocker.patch("rs_server_catalog.utils.is_s3_path", return_value=True)
        mock_s3_handler = mocker.Mock()
        mock_s3_handler.delete_file_from_s3.side_effect = RuntimeError("Deletion failed")
        mock_get_s3_handler.return_value = mock_s3_handler
        ftbd = "s3://bucket_name/path/to/file"
        result = delete_s3_files([ftbd])

        assert result is True  # Function should continue even if deletion fails
        mock_logger.exception.assert_called_once_with(
            f"Failed to delete key {ftbd} from s3 bucket."
            "Reason: Deletion failed. However, the process will still continue !",
        )


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
        # Mock S3StorageHandler and its delete_file_from_s3 method
        mocker.patch.dict(
            os.environ,
            {
                "S3_ACCESSKEY": "fake_access_key",
                "S3_SECRETKEY": "fake_secret_key",
                "S3_ENDPOINT": "https://fake_endpoint",
                "S3_REGION": "fake_region",
            },
        )

        mock_s3_handler = mocker.patch("rs_server_catalog.utils.S3StorageHandler")
        s3_handler = get_s3_handler()

        # Assertions
        assert s3_handler is not None
        mock_s3_handler.assert_called_once_with(
            "fake_access_key",
            "fake_secret_key",
            "https://fake_endpoint",
            "fake_region",
        )

    def test_s3_handler_missing_env_variables(self, mocker, capsys):
        """Test that missing environment variables return None and print an error."""
        # Clear environment variables
        mocker.patch.dict(os.environ, {}, clear=True)
        # Call the function and capture output
        s3_handler = get_s3_handler()
        captured = capsys.readouterr()

        # Assertions
        assert s3_handler is None
        assert "Failed to find s3 credentials when trying to create the s3 handler" in captured.out

    def test_s3_handler_creation_runtime_error(self, mocker, capsys):
        """Test that a RuntimeError during s3_handler creation returns None and prints an error."""
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
        mock_s3_handler = mocker.patch("rs_server_catalog.utils.S3StorageHandler", side_effect=RuntimeError)

        # Call the function and capture output
        s3_handler = get_s3_handler()
        captured = capsys.readouterr()

        # Assertions
        assert s3_handler is None
        assert "Failed to create the s3 handler" in captured.out
        mock_s3_handler.assert_called_once()
