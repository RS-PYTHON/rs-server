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

"""Exercise mission filters through STAC, EODAG and a station with decoy products."""

import itertools
import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
import yaml
from dateutil.parser import isoparse
from eodag.api.search_result import SearchResult
from eodag.plugins.search.qssearch import ODataV4Search
from eodag.utils.exceptions import MisconfiguredError
from pygeofilter.backends.native.evaluate import NativeEvaluator
from pygeofilter.parsers.cql2_text import parse
from rs_server_adgs import adgs_utils
from rs_server_common.data_retrieval.eodag_provider import (
    CustomEODataAccessGateway,
    EodagProvider,
)
from rs_server_common.stac_api_common import prepare_product_search_params
from rs_server_common.utils.pytest.pytest_utils import create_mock_collection
from rs_server_prip import prip_utils

from tests.app import ROUTER_PREFIX_AUXIP, ROUTER_PREFIX_PRIP

SATELLITES = {
    "sentinel-1a": ("SENTINEL-1", "A"),
    "sentinel-1b": ("SENTINEL-1", "B"),
    "sentinel-1c": ("SENTINEL-1", "C"),
    "sentinel-2a": ("SENTINEL-2", "A"),
    "sentinel-2b": ("SENTINEL-2", "B"),
    "sentinel-3a": ("SENTINEL-3", "A"),
    "sentinel-5p": ("SENTINEL-5P", None),
}


@pytest.mark.parametrize("service", ["adgs", "prip"])
@pytest.mark.parametrize("predeclared", [False, True], ids=["legacy-yaml", "already-declared"])
def test_internal_filters_with_existing_station_config(tmp_path, service, predeclared):
    """Existing YAMLs work without migration; previously added declarations do not duplicate filters."""
    source = Path(__file__).parents[1] / "services" / service / "config" / f"{service}_ws_config.yaml"
    configuration = yaml.safe_load(source.read_text())
    for provider in configuration.values():
        search = provider["search"]
        for name in ("missionFilter", "collectionFilter"):
            assert name not in search["metadata_mapping"]
            assert f"{{{name}}}" not in search["free_text_search_operations"]["$filter"]["operations"]["and"]
            if predeclared:
                search["metadata_mapping"][name] = [None, f"$.{name}"]
                search["free_text_search_operations"]["$filter"]["operations"]["and"].append(f"{{{name}}}")
    config_path = tmp_path / source.name
    original = yaml.safe_dump(configuration)
    config_path.write_text(original)
    gateway = CustomEODataAccessGateway.create(config_path.as_posix())
    assert CustomEODataAccessGateway.create(config_path.as_posix()) is gateway

    # Exercise every station in the file, including the second provider on the shared gateway.
    for name, configured in configuration.items():
        provider = gateway.providers[name]
        search = deepcopy(provider.config.search)
        search.products = deepcopy(provider.config.products)
        serializer = ODataV4Search(name, search)
        query, _ = serializer.build_query_string(
            next(iter(configured["products"])),
            {
                "attr_ptype": "'RAW'",
                "missionFilter": "(Name eq 'mission')",
                "collectionFilter": "(Name eq 'collection')",
            },
        )
        odata_filter = " and ".join(query["$filter"])
        assert odata_filter.count("(Name eq 'mission')") == 1
        assert odata_filter.count("(Name eq 'collection')") == 1
        assert "att/Name eq 'productType'" in odata_filter
        assert "Value eq 'RAW'" in odata_filter
        assert "missionFilter" not in str(query)
        assert "collectionFilter" not in str(query)
    assert config_path.read_text() == original


@pytest.mark.parametrize("service", ["adgs", "prip"])
def test_incompatible_filter_configuration_fails_at_initialization(tmp_path, service):
    """An unsupported filter layout must not silently drop the satellite restrictions."""
    source = Path(__file__).parents[1] / "services" / service / "config" / f"{service}_ws_config.yaml"
    configuration = yaml.safe_load(source.read_text())
    search = next(iter(configuration.values()))["search"]
    search.pop("free_text_search_operations")
    config_path = tmp_path / source.name
    config_path.write_text(yaml.safe_dump(configuration))
    with pytest.raises(MisconfiguredError, match="internal filters require a single OData AND group"):
        CustomEODataAccessGateway.create(config_path.as_posix())


def test_internal_filters_leave_cadip_configuration_unchanged():
    """CADIP uses complete satellite codes and does not need AUXIP/PRIP fragments."""
    source = Path(__file__).parents[1] / "services/cadip/config/cadip_ws_config.yaml"
    configuration = yaml.safe_load(source.read_text())
    gateway = CustomEODataAccessGateway.create(source.as_posix())
    for name, configured in configuration.items():
        search = gateway.providers[name].config.search
        assert search.free_text_search_operations == configured["search"]["free_text_search_operations"]
        assert not {"missionFilter", "collectionFilter"}.intersection(search.metadata_mapping)


def station_predicate(odata_filter):
    """Translate OData attribute comparisons to CQL and evaluate their Boolean grouping independently."""
    if not odata_filter:
        return lambda _: True
    cql = re.sub(
        r"Attributes/OData\.CSC\.StringAttribute/any\(att:att/Name eq '(\w+)' and "
        r"att/OData\.CSC\.StringAttribute/Value (eq '[^']*'|in \([^)]*\))\)",
        lambda match: match[1] + " " + match[2].replace("eq ", "= ", 1),
        odata_filter,
    )
    assert "Attributes/" not in cql, odata_filter
    return NativeEvaluator(use_getattr=False).evaluate(parse(cql))


def mock_collections(mocker, service, queries):
    """Expose the same operator-defined collections through listing and selection."""
    service_utils = adgs_utils if service == "adgs" else prip_utils
    collections = [create_mock_collection(service, service_utils, f"col_{i}", q) for i, q in enumerate(queries)]
    mocker.patch(
        "rs_server_common.stac_api_common.MockPgstac.all_collections",
        new_callable=mocker.PropertyMock,
        return_value=lambda: collections,
    )
    mocker.patch(f"{service_utils.__name__}.read_conf", return_value={"collections": collections})
    return collections


def station_product(template, index, platform, product_type=None):
    """Create a valid station product, including satellites without a serial attribute."""
    constellation, serial = SATELLITES[platform]
    product = deepcopy(template)
    product["Id"] = f"00000000-0000-0000-0000-{index:012d}"
    product["Name"] = platform if product_type is None else f"{platform}_{product_type}"
    values = {"platformShortName": constellation, "platformSerialIdentifier": serial}
    if product_type:
        values["productType"] = product_type
    for attr in product["Attributes"]:
        if attr["Name"] in values:
            attr["Value"] = values[attr["Name"]]
    if serial is None:
        product["Attributes"] = [a for a in product["Attributes"] if a["Name"] != "platformSerialIdentifier"]
    return product


@pytest.mark.parametrize(
    "fastapi_app,service",
    [(ROUTER_PREFIX_AUXIP, "adgs"), (ROUTER_PREFIX_PRIP, "prip")],
    indirect=["fastapi_app"],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("explicit_collections", [True, False], ids=["explicit-collections", "all-collections"])
@pytest.mark.parametrize(
    "queries,platforms,constellations,expected",
    [
        ([{}], ["sentinel-1c", "sentinel-2b", "sentinel-3a"], None, {"sentinel-1c", "sentinel-2b", "sentinel-3a"}),
        (
            [{"platformShortName": "sentinel-1,sentinel-2", "platformSerialIdentifier": "A,B"}],
            ["sentinel-1c", "sentinel-2b", "sentinel-3a"],
            None,
            {"sentinel-2b"},
        ),
        ([{"platform": ["sentinel-1a", "sentinel-2b"]}], None, None, {"sentinel-1a", "sentinel-2b"}),
        (
            [{"platform": ["sentinel-1a", "sentinel-2b"]}],
            ["sentinel-1c", "sentinel-2b", "sentinel-3a"],
            None,
            {"sentinel-2b"},
        ),
        (
            [{"platform": ["sentinel-1b", "sentinel-2a"]}],
            ["sentinel-1a", "sentinel-2b"],
            None,
            set(),
        ),
        (
            [{"platform": ["sentinel-1b", "sentinel-2a"]}, {"platform": "sentinel-1a"}],
            ["sentinel-1a", "sentinel-2b"],
            None,
            {"sentinel-1a"},
        ),
        (
            [{"platformShortName": "sentinel-1", "platformSerialIdentifier": "A"}, {"platform": "sentinel-2b"}],
            None,
            None,
            {"sentinel-1a", "sentinel-2b"},
        ),
        ([{}], ["sentinel-1a", "sentinel-1c", "sentinel-1a"], None, {"sentinel-1a", "sentinel-1c"}),
        (
            [{}],
            None,
            ["sentinel-1", "sentinel-2"],
            {"sentinel-1a", "sentinel-1b", "sentinel-1c", "sentinel-2a", "sentinel-2b"},
        ),
        ([{}], ["sentinel-1c", "sentinel-2b"], ["sentinel-2"], {"sentinel-2b"}),
        ([{}], ["sentinel-1c", "sentinel-5p"], None, {"sentinel-1c", "sentinel-5p"}),
        (
            [
                {
                    "platform": " SENTINEL-1A, sentinel-2b ",
                    "platformShortName": "SENTINEL-2",
                    "platformSerialIdentifier": "b",
                },
            ],
            None,
            None,
            {"sentinel-2b"},
        ),
        ([{"platform": []}], None, None, set()),
        ([{"platform": "sentinel-1a"}, {}], None, None, set(SATELLITES)),
    ],
    ids=[
        "unconfigured",
        "legacy-intersection",
        "configured-pairs",
        "pair-intersection",
        "empty-despite-overlapping-projections",
        "discard-empty-branch",
        "multiple-collections",
        "same-constellation-and-duplicates",
        "constellations-only",
        "platform-and-constellation",
        "missing-serial",
        "configured-case-and-legacy-intersection",
        "empty-configured-platforms",
        "unrestricted-collection-in-union",
    ],
)
def test_mission_search(  # pylint: disable=too-many-arguments,too-many-locals
    mocker,
    client,
    service,
    method,
    explicit_collections,
    queries,
    platforms,
    constellations,
    expected,
    adgs_response,
    prip_response,
):
    """Filter exact mission identities with explicit collections and with all collections selected implicitly."""
    collections = mock_collections(mocker, service, queries)
    template = (adgs_response if service == "adgs" else prip_response)["value"][0]
    products = [station_product(template, i, platform) for i, platform in enumerate(SATELLITES)]

    station_matches: list[str] = []

    def station_response(request):
        query = parse_qs(urlsplit(request.url).query)
        assert "missionFilter" not in request.url and "collectionFilter" not in request.url
        predicate = station_predicate(query.get("$filter", [""])[0])
        selected = [p for p in products if predicate({a["Name"]: a["Value"] for a in p["Attributes"]})]
        station_matches.extend(p["Name"] for p in selected)
        return 200, {"Content-Type": "application/json"}, json.dumps({"value": selected})

    filters = {key: value for key, value in (("platform", platforms), ("constellation", constellations)) if value}
    params: dict = {"collections": [c["id"] for c in collections]} if explicit_collections else {}
    with responses.RequestsMock() as station:
        if expected:
            station.add_callback(responses.GET, re.compile(r"http://127\.0\.0\.1:5000/Products\?"), station_response)
        # Empty intersections must avoid station calls; any unexpected HTTP request fails the test.
        if method == "GET":
            if explicit_collections:
                params["collections"] = ",".join(params["collections"])
            if filters:
                params["filter"] = " and ".join(
                    f"{key} in (" + ",".join(f"'{value}'" for value in values) + ")" for key, values in filters.items()
                )
            response = client.get(f"/{'auxip' if service == 'adgs' else 'prip'}/search", params=params)
        else:
            if filters:
                params["filter"] = {
                    "op": "and",
                    "args": [{"op": "in", "args": [{"property": key}, values]} for key, values in filters.items()],
                }
            response = client.post(f"/{'auxip' if service == 'adgs' else 'prip'}/search", json=params)
        assert response.status_code == 200, response.text
        search_calls = [call for call in station.calls if "/Products?" in (call.request.url or "")]
        assert len(search_calls) == bool(expected)
    assert set(station_matches) == expected
    assert {item["properties"]["platform"] for item in response.json()["features"]} == expected


@pytest.mark.parametrize(
    "fastapi_app,service",
    [(ROUTER_PREFIX_AUXIP, "adgs"), (ROUTER_PREFIX_PRIP, "prip")],
    indirect=["fastapi_app"],
)
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("explicit_collections", [True, False], ids=["explicit-collections", "all-collections"])
def test_collection_union_keeps_product_types_before_pagination(
    mocker,
    client,
    service,
    method,
    explicit_collections,
    adgs_response,
    prip_response,
):
    """Crossed platform/type combinations must not consume a page or hide a valid product."""
    template = (adgs_response if service == "adgs" else prip_response)["value"][0]
    product_type = next(a["Value"] for a in template["Attributes"] if a["Name"] == "productType")
    other_type = "AUX_PP2" if service == "adgs" else "OPER_MSI_L0"
    queries = [
        {"platform": ["sentinel-1a", "sentinel-2b"], "productType": product_type},
        {"platform": "sentinel-3a", "productType": other_type},
        # Overlapping collections must not duplicate items.
        {"platform": ["sentinel-1a", "sentinel-2b"], "productType": product_type},
    ]
    collections = mock_collections(mocker, service, queries)
    samples = [
        ("sentinel-1a", other_type),  # Newest product, but outside both collections.
        ("sentinel-1a", product_type),
        ("sentinel-3a", product_type),
        ("sentinel-3a", other_type),
        ("sentinel-1b", product_type),  # Decoys also check missionFilter inside collectionFilter.
        ("sentinel-2a", product_type),
    ]
    products = [station_product(template, i, platform, ptype) for i, (platform, ptype) in enumerate(samples)]
    for i, product in enumerate(products):
        product["PublicationDate"] = product["OriginDate"] = f"2024-08-{10 - i:02d}T00:00:00Z"

    station_queries = []

    def station_response(request):
        query = parse_qs(urlsplit(request.url).query)
        assert "missionFilter" not in request.url and "collectionFilter" not in request.url
        station_queries.append(query)
        predicate = station_predicate(query["$filter"][0])
        selected = [p for p in products if predicate({a["Name"]: a["Value"] for a in p["Attributes"]})]
        # Apply OData filtering before slicing the page, as the station does.
        # Local filtering alone would let the newest decoy consume page 1 and hide a valid product.
        assert [p["Name"] for p in selected] == [products[1]["Name"], products[3]["Name"]]
        skip, limit = int(query["$skip"][0]), int(query["$top"][0])
        return 200, {"Content-Type": "application/json"}, json.dumps({"value": selected[skip : skip + limit]})

    endpoint = f"/{'auxip' if service == 'adgs' else 'prip'}/search"
    with responses.RequestsMock() as station:
        station.add_callback(responses.GET, re.compile(r"http://127\.0\.0\.1:5000/Products\?"), station_response)
        for page, expected_product in ((1, products[1]), (2, products[3])):
            params: dict = {"limit": 1}
            if explicit_collections:
                params["collections"] = [c["id"] for c in collections]
            if page == 2:
                params["token"] = "next:page=2"
            if method == "GET":
                if explicit_collections:
                    params["collections"] = ",".join(params["collections"])
                response = client.get(endpoint, params=params)
            else:
                response = client.post(endpoint, json=params)
            assert response.status_code == 200, response.text
            assert [item["id"] for item in response.json()["features"]] == [expected_product["Name"]]
    assert len(station_queries) == 2
    assert station_queries[0]["$filter"] == station_queries[1]["$filter"]
    # /search fetches the first limit * page items per station, then sorts and slices the combined results locally.
    assert [q["$top"] for q in station_queries] == [["1"], ["2"]]
    assert all(q["$skip"] == ["0"] for q in station_queries)


@pytest.mark.parametrize(
    "case,expected,geometry_count",
    [
        (
            "shared-geometry-and-pairs",
            "spatial and ((platformShortName = 'SENTINEL-1' and platformSerialIdentifier = 'A') or "
            "(platformShortName = 'SENTINEL-2' and platformSerialIdentifier = 'B')) "
            "and productType in ('RAW','OTHER')",
            1,
        ),
        ("geometry-in-one-branch", "(spatial and productType = 'RAW') or productType = 'OTHER'", 1),
        ("unrestricted-remainder", "spatial", 1),
        (
            "different-pairs-and-types",
            "(platformShortName = 'SENTINEL-1' and platformSerialIdentifier = 'A' and productType = 'RAW') or "
            "(platformShortName = 'SENTINEL-2' and platformSerialIdentifier = 'B' and productType = 'OTHER')",
            0,
        ),
        (
            "shared-start-with-different-ends",
            "content_start >= TIMESTAMP('2024-01-01T00:00:00Z') and "
            "((productType = 'RAW' and content_end <= TIMESTAMP('2024-01-03T00:00:00Z')) or "
            "(productType = 'OTHER' and content_end <= TIMESTAMP('2024-01-05T00:00:00Z')))",
            0,
        ),
    ],
)
def test_collection_filter_factors_common_predicates(mocker, case, expected, geometry_count):
    """Emit common predicates once while preserving each collection's remaining restrictions."""
    geometry = "POLYGON((0 0,1 0,1 1,0 0))"
    pairs = (("SENTINEL-1", "A"), ("SENTINEL-2", "B"))
    queries = {
        "shared-geometry-and-pairs": [
            {"intersects": geometry, "mission_pairs": pairs, "productType": "RAW"},
            {"intersects": geometry, "mission_pairs": pairs, "productType": "OTHER"},
        ],
        "geometry-in-one-branch": [
            {"intersects": geometry, "productType": "RAW"},
            {"productType": "OTHER"},
        ],
        "unrestricted-remainder": [{"intersects": geometry, "productType": "RAW"}, {"intersects": geometry}],
        "different-pairs-and-types": [
            {"mission_pairs": (pairs[0],), "productType": "RAW"},
            {"mission_pairs": (pairs[1],), "productType": "OTHER"},
        ],
        "shared-start-with-different-ends": [
            {"Start": "2024-01-01T00:00:00Z", "End": "2024-01-03T00:00:00Z", "productType": "RAW"},
            {"Start": "2024-01-01T00:00:00Z", "End": "2024-01-05T00:00:00Z", "productType": "OTHER"},
        ],
    }
    source = Path(__file__).parents[1] / "services/prip/config/prip_ws_config.yaml"
    gateway = CustomEODataAccessGateway.create(source.as_posix())
    provider = object.__new__(EodagProvider)
    provider.client, provider.provider = gateway, "s2b"
    search = mocker.patch.object(gateway, "search", return_value=SearchResult([]))
    params = prepare_product_search_params({"query_branches": queries[case]})
    original = deepcopy(params)
    provider._specific_search(**params, limit=10)  # pylint: disable=protected-access
    assert params == original
    search.assert_called_once()
    odata_filter = search.call_args.kwargs["collectionFilter"]
    assert odata_filter.count("OData.CSC.Intersects") == geometry_count
    if case == "shared-geometry-and-pairs":
        assert odata_filter.count("Value eq 'SENTINEL-1'") == 1
        assert odata_filter.count("Value eq 'SENTINEL-2'") == 1

    # Evaluate the final Boolean grouping independently, including products outside the common geometry.
    cql = re.sub(r"OData\.CSC\.Intersects\(area=geography'[^']*'\)", "(spatial = TRUE)", odata_filter)
    operators = {"eq": "=", "gt": ">", "lt": "<"}
    cql = re.sub(
        r"ContentDate/(Start|End) (eq|gt|lt) ([^\s)]+)",
        lambda match: f"content_{match[1].lower()} {operators[match[2]]} TIMESTAMP('{match[3]}')",
        cql,
    )
    predicate = station_predicate(cql)
    expected_predicate = NativeEvaluator(use_getattr=False).evaluate(
        parse(re.sub(r"\bspatial\b", "(spatial = TRUE)", expected)),
    )
    for pair, product_type, spatial, start, end in itertools.product(
        [("SENTINEL-1", "A"), ("SENTINEL-1", "B"), ("SENTINEL-2", "A"), ("SENTINEL-2", "B")],
        ["RAW", "OTHER", "DECOY"],
        [False, True],
        ["2023-12-31T00:00:00Z", "2024-01-02T00:00:00Z"],
        ["2024-01-02T00:00:00Z", "2024-01-04T00:00:00Z", "2024-01-06T00:00:00Z"],
    ):
        row = {
            "platformShortName": pair[0],
            "platformSerialIdentifier": pair[1],
            "productType": product_type,
            "spatial": spatial,
            "content_start": isoparse(start),
            "content_end": isoparse(end),
        }
        assert predicate(row) == expected_predicate(row), (case, row, odata_filter)
