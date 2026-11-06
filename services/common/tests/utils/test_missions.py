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

"""Mission selection semantics independent of the station and transport."""

from copy import deepcopy

import pytest
from fastapi import HTTPException
from rs_server_common.data_retrieval.eodag_provider import EodagProvider
from rs_server_common.utils.missions import (
    extract_missions,
    intersect_missions,
    matches_mission,
    mission_search_params,
)


def test_pair_intersection_does_not_intersect_projections():
    """S1A/S2B and S1B/S2A have no common pair, despite containing the same constellations and serials."""
    _, left = extract_missions({"platform": ["sentinel-1a", "sentinel-2b"]})
    _, right = extract_missions({"platform": ["sentinel-1b", "sentinel-2a"]})
    assert intersect_missions(left, right) == ()
    assert intersect_missions(left, None) == left
    assert intersect_missions(left, ()) == ()


def test_constellation_restrictions_do_not_enumerate_known_satellites():
    """A constellation wildcard must also match serials introduced after deployment."""
    _, selected = extract_missions({"platformShortName": "sentinel-1"})
    assert matches_mission({"platformShortName": "SENTINEL-1", "platformSerialIdentifier": "Z"}, selected)
    assert not matches_mission({"platformShortName": "SENTINEL-2", "platformSerialIdentifier": "Z"}, selected)
    assert mission_search_params(selected) == {"platformShortName": ["SENTINEL-1"]}


def test_legacy_lists_remain_independent():
    """Legacy configurations cannot silently acquire positional pairing semantics."""
    query = {"platformShortName": "sentinel-1,sentinel-2", "platformSerialIdentifier": "a,b", "productType": "RAW"}
    original = deepcopy(query)
    remaining, selected = extract_missions(query)
    assert query == original
    assert remaining == {"productType": "RAW"}
    assert selected == (("SENTINEL-1", "A"), ("SENTINEL-1", "B"), ("SENTINEL-2", "A"), ("SENTINEL-2", "B"))
    assert not matches_mission({"platformShortName": "SENTINEL-1", "platformSerialIdentifier": "C"}, selected)


@pytest.mark.parametrize("configured", [[], "sentinel-1a", "sentinel-1a,sentinel-2b", ["sentinel-1a", "sentinel-2b"]])
def test_explicit_platforms_do_not_broaden_collection_membership(configured):
    """Collection assignment must reject the cross-product decoys as well."""
    _, selected = extract_missions({"platform": configured})
    assert not matches_mission({"platformShortName": "SENTINEL-1", "platformSerialIdentifier": "B"}, selected)
    assert not matches_mission({"platformShortName": "SENTINEL-2", "platformSerialIdentifier": "A"}, selected)


@pytest.mark.parametrize("configured", ["unknown", "", "sentinel-1a,", [None], 42, {"sentinel-1a": True}])
def test_invalid_platform_configuration(configured):
    """Invalid restrictions must fail rather than turn into an unrestricted query."""
    with pytest.raises(HTTPException):
        extract_missions({"platform": configured})


def test_serial_only_and_missing_serial():
    """Intersect a serial restriction with complete pairs and allow Sentinel-5P products without a serial."""
    _, selected = extract_missions({"platform": ["sentinel-1a", "sentinel-2b"], "platformSerialIdentifier": "b"})
    assert selected == (("SENTINEL-2", "B"),)
    _, selected = extract_missions({"platform": ["sentinel-1a", "sentinel-5p"]})
    assert matches_mission({"platformShortName": "SENTINEL-5P"}, selected)
    assert not matches_mission({"platformShortName": "SENTINEL-1"}, selected)
    assert "'None'" not in mission_search_params(selected)["missionFilter"]


def test_odata_literal_escaping():
    """Internal OData fragments must escape quotes in configured attribute values."""
    fragment = mission_search_params((("O'NEIL", "A"), ("OTHER", "B")))["missionFilter"]
    assert "Value eq 'O''NEIL'" in fragment
    params = mission_search_params((("O'NEIL", "A"),))
    provider = object.__new__(EodagProvider)
    mapped = provider._map_search_args(params)  # pylint: disable=protected-access
    assert mapped["platformShortName"] == "'O''NEIL'"
