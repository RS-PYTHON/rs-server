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


def test_escape_like_literal():
    """Escapes SQL LIKE wildcards and backslashes."""
    assert rm.escape_like_literal(r"S03_2025%a\b") == r"S03\_2025\%a\\b"


@pytest.mark.parametrize(
    "raw_ids, expected",
    [
        ("a,b,a,", ["a", "b"]),
        (["a", "", "b", "a"], ["a", "b"]),
        ("", None),
        ([], None),
        (None, None),
        (123, None),
        (["a", 123], None),
    ],
)
def test_parse_search_ids(raw_ids, expected):
    """Parses GET strings and POST lists, deduplicating while ignoring empty or invalid values."""
    assert rm.parse_search_ids(raw_ids) == expected


def test_translate_ids_search_without_existing_filter():
    """Translates ids into exact-or-extension CQL2-JSON filter with escaped LIKE patterns."""
    result = rm.translate_ids_search(None, "cql2-json", ["S03_ITEM1", "ITEM2"])
    assert result == {
        "op": "or",
        "args": [
            {"op": "=", "args": [{"property": "id"}, "S03_ITEM1"]},
            {"op": "like", "args": [{"property": "id"}, r"S03\_ITEM1.%"]},
            {"op": "=", "args": [{"property": "id"}, "ITEM2"]},
            {"op": "like", "args": [{"property": "id"}, "ITEM2.%"]},
        ],
    }
    # Ensure stac-fastapi-pgstac's cql2 validator accepts the generated filter.
    rm.cql2.Expr(result).validate()  # pylint: disable=no-member


def test_translate_ids_search_combines_with_existing_filter():
    """Combines translated ids filter with an existing filter via AND."""
    existing = {"op": "=", "args": [{"property": "product:type"}, "S03OLCIL0"]}
    result = rm.translate_ids_search(existing, "cql2-json", "S03_ITEM1")
    assert result == {
        "op": "and",
        "args": [
            existing,
            {
                "op": "or",
                "args": [
                    {"op": "=", "args": [{"property": "id"}, "S03_ITEM1"]},
                    {"op": "like", "args": [{"property": "id"}, r"S03\_ITEM1.%"]},
                ],
            },
        ],
    }


def test_translate_ids_search_empty_returns_none():
    """Returns None when ids are absent or empty."""
    assert rm.translate_ids_search(None, "cql2-text", "") is None
    assert rm.translate_ids_search(None, "cql2-json", []) is None


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
