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

"""Unit tests for request_manager helpers."""

import json

import pytest
from fastapi import HTTPException
from rs_server_catalog.middleware import request_manager as rm


def test_iter_external_id_parts_splits_and_strips():
    """Splits comma-separated externalIds and trims whitespace."""
    parts = rm.iter_external_id_parts("cadip:123, auxip:456,,  ")
    assert parts == ["cadip:123", "auxip:456"]


def test_iter_external_id_parts_list_input():
    """Accepts lists and flattens comma-separated values."""
    parts = rm.iter_external_id_parts(["cadip:123", " auxip:456,prip:789", None])
    assert parts == ["cadip:123", "auxip:456", "prip:789"]


def test_build_external_ids_tokens_dedup_and_formats():
    """Normalizes tokens and removes duplicates."""
    tokens = rm.build_external_ids_tokens("cadip:123, cadip:123, auxip:, 456")
    assert tokens == ["cadip:123", "auxip", "456"]


def test_build_external_ids_filter_none_when_empty():
    """Returns None when no externalIds tokens are available."""
    assert rm.build_external_ids_filter("") is None


def test_build_external_ids_filter_builds_overlap():
    """Builds an a_overlaps CQL2 filter for externalIds."""
    result = rm.build_external_ids_filter("cadip:123,456")
    assert result == {
        "op": "a_overlaps",
        "args": [{"property": "externalIds"}, ["cadip:123", "456"]],
    }


def test_parse_filter_to_json_cql2_json_string():
    """Parses JSON CQL2 string into a dict."""
    raw = json.dumps({"op": "=", "args": [{"property": "owner"}, "toto"]})
    result = rm.parse_filter_to_json(raw, "cql2-json")
    assert result == {"op": "=", "args": [{"property": "owner"}, "toto"]}


def test_parse_filter_to_json_cql2_text(monkeypatch):
    """Parses CQL2-text via cql2.parse_text()."""

    class ParsedFilter:  # pylint: disable=too-few-public-methods
        """Simple stub returned by parse_text() in tests."""

        def to_json(self):
            """Return a minimal CQL2-JSON structure."""
            return {"op": "=", "args": [{"property": "owner"}, "toto"]}

    monkeypatch.setattr(rm.cql2, "parse_text", lambda _: ParsedFilter())
    result = rm.parse_filter_to_json("owner='toto'", "cql2-text")
    assert result == {"op": "=", "args": [{"property": "owner"}, "toto"]}


def test_combine_filters_with_existing():
    """Combines two filters with AND."""
    existing = {"op": "=", "args": [{"property": "owner"}, "toto"]}
    extra = {"op": "=", "args": [{"property": "width"}, 2500]}
    combined = rm.combine_filters(existing, extra)
    assert combined == {"op": "and", "args": [existing, extra]}


def test_combine_filters_without_existing():
    """Returns extra filter when no existing filter is present."""
    extra = {"op": "=", "args": [{"property": "width"}, 2500]}
    assert rm.combine_filters(None, extra) == extra


def test_filter_has_external_ids_true():
    """Detects externalIds presence in filter."""
    filter_json = {"op": "=", "args": [{"property": "externalIds"}, "123"]}
    assert rm.filter_has_external_ids(filter_json) is True


def test_filter_has_external_ids_false():
    """Returns False when externalIds is not referenced."""
    filter_json = {"op": "=", "args": [{"property": "owner"}, "toto"]}
    assert rm.filter_has_external_ids(filter_json) is False


def test_normalize_external_ids_in_filter_converts_eq():
    """Converts externalIds '=' to a_overlaps with tokens."""
    filter_json = {"op": "=", "args": [{"property": "externalIds"}, "cadip:123,456"]}
    normalized = rm.normalize_external_ids_in_filter(filter_json)
    assert normalized == {
        "op": "a_overlaps",
        "args": [{"property": "externalIds"}, ["cadip:123", "456"]],
    }


def test_normalize_external_ids_in_filter_recurses_and():
    """Recurses through composite filters and rewrites externalIds."""
    filter_json = {
        "op": "and",
        "args": [
            {"op": "=", "args": [{"property": "owner"}, "toto"]},
            {"op": "=", "args": [{"property": "externalIds"}, "auxip:456"]},
        ],
    }
    normalized = rm.normalize_external_ids_in_filter(filter_json)
    assert normalized["args"][1] == {
        "op": "a_overlaps",
        "args": [{"property": "externalIds"}, ["auxip:456"]],
    }


def test_normalize_external_ids_filter_value_changes():
    """Normalizes raw filter input and flags a change."""
    raw_filter = {"op": "=", "args": [{"property": "externalIds"}, "auxip:456"]}
    normalized, lang, changed = rm.normalize_external_ids_filter_value(raw_filter, "cql2-json")
    assert changed is True
    assert lang == "cql2-json"
    assert normalized == {
        "op": "a_overlaps",
        "args": [{"property": "externalIds"}, ["auxip:456"]],
    }


def test_normalize_external_ids_filter_value_no_change():
    """Leaves unrelated filters unchanged."""
    raw_filter = {"op": "=", "args": [{"property": "owner"}, "toto"]}
    normalized, lang, changed = rm.normalize_external_ids_filter_value(raw_filter, "cql2-json")
    assert changed is False
    assert lang == "cql2-json"
    assert normalized == raw_filter


@pytest.mark.asyncio
async def test_manage_delete_request_s3_cleanup_retries_exhausted(mocker):
    """Return HTTP 500 after the retry of an S3 cleanup failure is exhausted."""
    request_path = "/catalog/collections/owner_collection/items/item"
    request = mocker.Mock(scope={"path": request_path})
    manager = rm.CatalogRequestManager(
        mocker.Mock(),
        {"owner_id": "owner", "collection_ids": ["collection"], "item_id": "item"},
    )
    manager.build_filelist_to_be_deleted = mocker.AsyncMock()
    # Fail both attempts to cover the retry warning and final HTTP 500 response.
    cleanup_error = RuntimeError("cleanup failed")
    delete_s3_files = mocker.AsyncMock(side_effect=cleanup_error)
    manager.s3_manager = mocker.Mock(return_value=mocker.Mock(delete_s3_files=delete_s3_files))
    mocker.patch.object(rm, "CATALOG_DELETE_MAX_RETRIES", 1)
    mocker.patch.object(rm.common_settings, "CLUSTER_MODE", False)
    mock_logger = mocker.patch.object(rm, "logger")

    with pytest.raises(HTTPException) as exc_info:
        await manager.manage_delete_request(request)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to delete S3 assets; catalog metadata was not deleted."
    # Cleanup targets are rebuilt before every complete retry.
    assert manager.build_filelist_to_be_deleted.await_count == 2
    assert delete_s3_files.await_count == 2
    mock_logger.warning.assert_called_once_with(
        "S3 cleanup attempt %d/%d failed for %s: %s. Rebuilding targets and retrying from scratch.",
        1,
        2,
        request_path,
        cleanup_error,
    )
    mock_logger.exception.assert_called_once_with(
        "S3 cleanup failed before catalog DELETE for %s after %d outer attempt(s)",
        request_path,
        2,
    )
