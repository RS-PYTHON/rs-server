# pylint: disable=too-many-lines

# Copyright 2023-2025 Airbus, CS Group
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

"""Unit tests for the authentication."""

import getpass
import itertools
import json
import os
from dataclasses import dataclass
from typing import Any, Literal

import pytest
import requests
from pytest_httpx import HTTPXMock
from rs_server_catalog.app import app, must_be_authenticated
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.pytest.pytest_authentication_utils import (
    VALID_APIKEY_HEADER,
    WRONG_APIKEY_HEADER,
    init_authentication_test,
)
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_302_FOUND,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from .helpers import (  # pylint: disable=no-name-in-module
    AUTH_EXTENSION,
    AUTH_REFS,
    AUTH_SCHEME,
    Collection,
    Feature,
    clear_aws_credentials,
)

TEST_STORAGE_CONFIG_DATA = [
    ["*", "*", "*", "30", "rspython-ops-catalog-all-production"],
    ["copernicus", "s1-l1", "*", "10", "rspython-ops-catalog-copernicus-s1-l1"],
    ["copernicus", "s1-aux", "*", "40", "rspython-ops-catalog-copernicus-s1-aux"],
    ["copernicus", "s1-aux", "orbsct", "7300", "rspython-ops-catalog-copernicus-s1-aux-infinite"],
]
####################
# Global variables #
####################

logger = Logging.default(__name__)

# Run tests by authenticating with either an apikey or oauth2 cookie
AUTH_PARAM = pytest.mark.parametrize(
    "test_apikey, test_oauth2",
    [[True, False], [False, True]],
    ids=["apikey", "oauth2"],
)

COMMON_FIELDS = {
    "extent": {
        "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
        "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
    },
    "license": "public-domain",
    "description": "Some description",
    "stac_version": "1.1.0",
    "stac_extensions": [AUTH_EXTENSION],
    **AUTH_SCHEME,
}

ActionType = Literal["read", "write", "download"]

#################################
# Utility classes and functions #
#################################


@dataclass
class AuthorizationInfo:
    """Authorization info linked to a database collection or to a user iam roles in UAC/Keycloak."""

    owner_id: str
    collection_id: str
    actions: ActionType | list[ActionType]


# All existing collections inserted in the database from conftest.py::setup_database
# with "read" authorization.
ALL_DATABASE_COLLECTIONS = [
    AuthorizationInfo("toto", "S1_L1", "read"),
    AuthorizationInfo("toto", "S2_L3", "read"),
    AuthorizationInfo("titi", "S1_L1", "read"),
    AuthorizationInfo("titi", "S2_L1", "read"),
    AuthorizationInfo("darius", "S1_L2", "read"),
    AuthorizationInfo("pyteam", "S1_L1", "read"),
    AuthorizationInfo(getpass.getuser(), "S2_L2", "read"),
]


def get_test_cases(  # pylint: disable=too-many-branches
    endpoint_desc: str,
    requested_collections: AuthorizationInfo | list[AuthorizationInfo],
    write_collections: bool = False,
    init_test_params: dict | None = None,
) -> pytest.MarkDecorator:
    """
    Generate all test cases for the catalog endpoint authorizations.

    For each endpoint, we test 3 test cases regarding the collections owner_id:
    1. The user has an iam role with owner_id=*, which allows him to request collections by all owners (test case=all)
    2. The user has an iam role with owner_id = the owner of the specific requested collection (test case=ok)
    3. The user has an iam role with a wrong owner_id (test case=ko).

    Same thing with the test cases for collection_id:
    1. * to request all collections
    2. Good collection_id
    3. Wrong collection_id

    Same thing for the action (read/write/download) but without the *:
    1. Good action
    2. Wrong action

    So for each endpoint we test all possible test case combinations 3*3*2 = 18 test cases, plus we add some
    specific test cases when possible:
    - implicit_owner (when the user is also the owner of the collection)
    - no_roles (error case when a user has no iam roles)
    - partial_roles (add authorization on only half the collections)

    Args:
        endpoint_desc, endpoint description
        requested_collections: database collections requested by the pytest. In the nominal test cases, we add iam
        roles to the user to give him authorization on these collections.
        write_collections: specific case when we want to POST/PUT/DELETE collections. In this case, the only test that
        should succeed is the implicit owner = the user is also the owner of the owner of all the requested collections.
        init_test_params: additional params to pass to the init_test() function.

    Returns:
        Parametrized test cases, ready to use with a pytest, with parameters:
        endpoint_desc: same as input arg.
        requested_collections: same as input arg, expect in the "partial_roles" case where we add authorization to
        only half the collections.
        user_login: UAC/Keycloak user and API key or oauth2 cookie owner.
        iam_roles: user iam (Identity and Access Management) roles in UAC/Keycloak.
        should_succeed: should the user be authorized for the requested collections using this user login and roles ?
        init_test_params: same as input arg.
    """

    # pytest parameters, values and ids
    param_names = [
        "endpoint_desc",
        "requested_collections",
        "user_login",
        "iam_roles",
        "should_succeed",
        "init_test_params",
    ]
    param_ids = []
    param_values = []

    # Only work with sorted lists
    if isinstance(requested_collections, AuthorizationInfo):
        requested_collections = [requested_collections]
    else:
        requested_collections.sort(key=lambda col: f"{col.owner_id}:{col.collection_id}")
    for requested_col in requested_collections:
        if isinstance(requested_col.actions, str):
            requested_col.actions = [requested_col.actions]
        else:
            requested_col.actions.sort()

    # Specific test case: implicit owner = the user is also the owner of the owner of all the requested collections.
    requested_col_owners = {col.owner_id for col in requested_collections}  # remove duplicates
    if len(requested_col_owners) == 1:
        param_ids.append("implicit_owner")
        param_values.append(
            [endpoint_desc, requested_collections, next(iter(requested_col_owners)), [], True, init_test_params],
        )

    # Test that with no roles at all, the user is unauthorized
    param_ids.append("no_roles")
    param_values.append([endpoint_desc, requested_collections, "anybody", [], False, init_test_params])

    # For every possible test case
    for test_owner, test_col_id, test_action in itertools.product(
        ["all", "ok", "ko"],
        ["all", "ok", "ko"],
        ["ok", "ko"],
    ):
        iam_roles = set()
        should_succeed = True

        # Calculate iam roles for the current test case and for all requested collections
        for requested_col in requested_collections:

            if test_owner == "all":
                iam_role_owner = "*"
            elif test_owner == "ok":
                iam_role_owner = requested_col.owner_id
            else:  # ko
                iam_role_owner = "unauth"
                should_succeed = False

            if test_col_id == "all":
                iam_role_col_id = "*"
            elif test_col_id == "ok":
                iam_role_col_id = requested_col.collection_id
            else:  # ko
                iam_role_col_id = "unauth"
                should_succeed = False

            # For "wrong" actions we'll use actions that are not requested for this requested collection
            ko_actions = list({"read", "write", "download"} - set(requested_col.actions))

            if test_action == "ok":
                iam_role_actions = requested_col.actions
            else:  # ko
                iam_role_actions = ko_actions  # type: ignore[assignment]
                should_succeed = False

            for iam_role_action in iam_role_actions:
                iam_roles.add(f"rs_catalog_{iam_role_owner}:{iam_role_col_id}_{iam_role_action}")

        # Add a dummy role, it should not impact the authorization
        iam_roles.add("rs_catalog_dummy:dummy_read")

        # Save pytest param ids and values for the current test case
        param_ids.append(f"owner_{test_owner}-col_{test_col_id}-action_{test_action}")
        param_values.append(
            [
                endpoint_desc,
                requested_collections,
                "anybody",
                sorted(iam_roles),
                should_succeed and (not write_collections),
                init_test_params,
            ],
        )

    # In the case of several requested collections, add a test case where everything is ok
    # but we only keep half the collections.
    if len(requested_collections) > 1:
        half_collections = requested_collections[0 : int(len(requested_collections) / 2)]
        iam_roles = {
            f"rs_catalog_{col.owner_id}:{col.collection_id}_{action}"
            for col in half_collections
            for action in col.actions
        }
        param_values.append(
            [
                endpoint_desc,
                half_collections,
                "anybody",
                sorted(iam_roles),
                True and (not write_collections),
                init_test_params,
            ],
        )
        param_ids.append("partial_roles")

    return pytest.mark.parametrize(param_names, param_values, ids=param_ids)


@pytest.fixture(scope="function", name="_init_authorization_test")
async def init_authorization_test(
    mocker,
    httpx_mock: HTTPXMock,
    client,
    test_apikey: bool,
    test_oauth2: bool,
    endpoint_desc: str,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    iam_roles: list[str],
    should_succeed: bool,
    init_test_params: dict,
):
    """
    Initialize a pytest to test the authorization. The arguments come from get_test_cases()
    """
    # Log test params
    log_collections = "\n  ".join(
        [""]
        + [
            f"'{col.owner_id}:{col.collection_id}' (needs {','.join(col.actions)!r} privileges)"
            for col in requested_collections
        ],
    )
    log_roles = "\n  ".join([""] + (iam_roles or ["(none)"]))
    logger.debug(
        f"""
I want to: {endpoint_desc!r}
As user: {user_login!r} (=UAC/Keycloak user and {'API key' if test_apikey else 'OAuth 2.0 cookie'} owner)
On collections: {log_collections}
With IAM roles: {log_roles}
Should this succeed ? {"Yes" if should_succeed else "No"}""",
    )

    # Init mockers for test
    await init_authentication_test(
        mocker,
        httpx_mock,
        client,
        test_apikey,
        test_oauth2,
        iam_roles,
        {},
        user_login=user_login,
        **(init_test_params or {}),
    )


@pytest.fixture(scope="function", name="_init_bucket_for_auth_download")
def init_bucket_for_auth_download(init_buckets_module):
    """Init the bucket only once for all the test_authorization_download test cases."""

    os.environ["RSPY_LOCAL_CATALOG_MODE"] = "0"

    s3_handler, moto_endpoint, _ = init_buckets_module
    requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
    object_content = "testing\n"

    def upload_object():
        """Upload a dummy file to the catalog bucket"""
        catalog_bucket = "rspython-ops-catalog-all-production"  # Name of default catalog from config file
        s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)
        s3_handler.s3_client.put_object(
            Bucket=catalog_bucket,
            Key="S1_L1/images/may24C355000e4102500n.tif",
            Body=object_content,
        )

    # Upload dummy file at the start of each test (scope="function")
    upload_object()
    yield {"object_content": object_content, "upload_object": upload_object}

    # Clear bucket at the end of the scope
    requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
    os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"


@pytest.fixture(scope="module", autouse=True)
def stop_bucket(init_buckets_module, client, feature_toto_s1_l1_0):
    """Clear bucket at the end of the scope (scope="module")"""

    _, _, server = init_buckets_module

    yield  # wait for the end of the scope
    server.stop()
    # Remove bucket credentials form env variables / should create a s3_handler without credentials error
    clear_aws_credentials()

    response = client.get(
        f"/catalog/collections/toto:S1_L1/items/{feature_toto_s1_l1_0.id_}/download/may24C355000e4102500n.tif",
    )
    assert response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert response.content == b'{"code":"InternalServerError","description":"Failed to find s3 credentials"}'


#########
# Tests #
#########


@AUTH_PARAM
@get_test_cases("GET landing page", ALL_DATABASE_COLLECTIONS, init_test_params={"mock_wrong_apikey": True})
async def test_authorization_landing_page(
    request,
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    should_succeed: bool,
):
    """Test the GET /catalog landing page endpoint"""

    # Test a wrong apikey
    if test_apikey:
        wrong_api_key_response = client.request("GET", "/catalog/", **WRONG_APIKEY_HEADER)
        assert wrong_api_key_response.status_code == HTTP_403_FORBIDDEN

    # Test with the good credentials
    header = VALID_APIKEY_HEADER if test_apikey else {}
    response = client.request("GET", "/catalog/", **header)

    # The endpoint should always return OK, even with wrong or missing roles
    assert response.status_code == HTTP_200_OK
    contents = json.loads(response.content)

    # Expected returned links
    expected_base_links = [
        {
            "rel": "self",
            "type": "application/json",
            "title": "This document",
            "href": "http://testserver/catalog/",
            **AUTH_REFS,
        },
        {
            "rel": "root",
            "type": "application/json",
            "title": "Root",
            "href": "http://testserver/catalog/",
            **AUTH_REFS,
        },
        {
            "rel": "data",
            "type": "application/json",
            "title": "Collections available for this Catalog",
            "href": "http://testserver/catalog/collections",
            **AUTH_REFS,
        },
        {
            "rel": "conformance",
            "type": "application/json",
            "title": "STAC/OGC conformance classes implemented by this server",
            "href": "http://testserver/catalog/conformance",
            **AUTH_REFS,
        },
        {
            "rel": "search",
            "type": "application/geo+json",
            "title": "STAC search [GET]",
            "href": "http://testserver/catalog/search",
            "method": "GET",
            **AUTH_REFS,
        },
        {
            "rel": "search",
            "type": "application/geo+json",
            "title": "STAC search [POST]",
            "href": "http://testserver/catalog/search",
            "method": "POST",
            **AUTH_REFS,
        },
        {
            "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "type": "application/schema+json",
            "title": "Queryables available for this Catalog",
            "href": "http://testserver/catalog/queryables",
            "method": "GET",
            **AUTH_REFS,
        },
        {
            "rel": "service-desc",
            "type": "application/vnd.oai.openapi+json;version=3.0",
            "title": "OpenAPI service description",
            "href": "http://testserver/catalog/api",
            **AUTH_REFS,
        },
        {
            "rel": "service-doc",
            "type": "text/html",
            "title": "OpenAPI service documentation",
            "href": "http://testserver/catalog/api.html",
            **AUTH_REFS,
        },
    ]

    # In nominal case, we should also have child links for all collections.
    # In error case, no collections should be returned.
    expected_col_links = []
    if should_succeed:

        # We request all the collections except for this specific test case
        if "partial_roles" not in request.node.name:
            assert requested_collections == ALL_DATABASE_COLLECTIONS
        expected_col_links = [
            {
                "rel": "child",
                "type": "application/json",
                "title": col.collection_id,
                "href": f"http://testserver/catalog/collections/{col.owner_id}:{col.collection_id}",
                **AUTH_REFS,
            }
            for col in requested_collections
        ]
    assert contents["links"] == expected_base_links + expected_col_links


@AUTH_PARAM
@get_test_cases("GET collections", ALL_DATABASE_COLLECTIONS)
async def test_authorization_get_collections(
    request,
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    should_succeed: bool,
):
    """Test the GET /catalog/collections endpoint"""

    header = VALID_APIKEY_HEADER if test_apikey else {}
    response = client.request("GET", "/catalog/collections", **header)

    # The endpoint should always return OK, even with wrong or missing roles
    assert response.status_code == HTTP_200_OK
    returned_cols = json.loads(response.content)["collections"]

    # In nominal case, all collections should be returned
    if should_succeed:

        # We request all the collections except for this specific test case
        if "partial_roles" not in request.node.name:
            assert requested_collections == ALL_DATABASE_COLLECTIONS

        expected_cols = [
            Collection(col.owner_id, col.collection_id).as_returned(cluster_mode=True) for col in requested_collections
        ]

        # For each collection returned, check that it has "created" and "updated" fields and remove them
        # (they have unpredictable values so can't be in the assert below)
        for index, collection in enumerate(returned_cols):
            assert "created" in collection
            assert "updated" in collection
            collection.pop("created")
            collection.pop("updated")
            returned_cols[index] = collection

        assert returned_cols == expected_cols

    # In error case, no collections should be returned
    else:
        assert not returned_cols


@AUTH_PARAM
@get_test_cases("GET one collection", AuthorizationInfo("toto", "S1_L1", "read"))
async def test_authorization_get_one_collection(
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    should_succeed: bool,
):
    """Test the GET /catalog/collections/{owner}:{collection_id} endpoint"""

    owner = requested_collections[0].owner_id
    collection_id = requested_collections[0].collection_id
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # The 'owner:' is needed in the url, except in the 'implicit owner' case (when user == collection owner)
    for owner_in_url in f"{owner}:", "":
        response = client.request("GET", f"/catalog/collections/{owner_in_url}{collection_id}", **header)

        # The implicit owner should work only when user == owner
        # Else we have a 404 because 'owner:' is missing from the url.
        if (not owner_in_url) and (user_login != owner):
            assert response.status_code == HTTP_404_NOT_FOUND

        elif should_succeed:
            assert response.status_code == HTTP_200_OK
            json_response = json.loads(response.content)

            # Test that "created" and "updated" fields are there and remove them because they have unpredictable values
            assert "created" in json_response
            assert "updated" in json_response
            json_response.pop("created")
            json_response.pop("updated")

            assert json_response == Collection(owner, collection_id).as_returned(cluster_mode=True)
        else:
            assert response.status_code == HTTP_401_UNAUTHORIZED


@AUTH_PARAM
@get_test_cases("GET items", AuthorizationInfo("toto", "S1_L1", "read"))
async def test_authorization_get_items(
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    should_succeed: bool,
    feature_toto_s1_l1_0,
    feature_toto_s1_l1_1,
):
    """Test the GET /catalog/collections/{owner}:{collection_id}/items endpoint"""

    owner = requested_collections[0].owner_id
    collection_id = requested_collections[0].collection_id
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # The 'owner:' is needed in the url, except in the 'implicit owner' case (when user == collection owner)
    for owner_in_url in f"{owner}:", "":
        response = client.request("GET", f"/catalog/collections/{owner_in_url}{collection_id}/items", **header)

        # The implicit owner should work only when user == owner
        # Else we have a 404 because 'owner:' is missing from the url.
        if (not owner_in_url) and (user_login != owner):
            assert response.status_code == HTTP_404_NOT_FOUND

        elif should_succeed:
            assert response.status_code == HTTP_200_OK
            returned_features = json.loads(response.content)["features"]
            assert [feature["id"] for feature in returned_features] == [
                feature_toto_s1_l1_0.id_,
                feature_toto_s1_l1_1.id_,
            ]
        else:
            assert response.status_code == HTTP_401_UNAUTHORIZED


@AUTH_PARAM
@get_test_cases("GET one item", AuthorizationInfo("toto", "S1_L1", "read"))
async def test_authorization_get_one_item(
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    should_succeed: bool,
    feature_toto_s1_l1_0,
):
    """Test the GET /catalog/collections/{owner}:{collection_id}/items/{item_id} endpoint"""

    owner = requested_collections[0].owner_id
    collection_id = requested_collections[0].collection_id
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # The 'owner:' is needed in the url, except in the 'implicit owner' case (when user == collection owner)
    for owner_in_url in f"{owner}:", "":
        response = client.request(
            "GET",
            f"/catalog/collections/{owner_in_url}{collection_id}/items/{feature_toto_s1_l1_0.id_}",
            **header,
        )

        # The implicit owner should work only when user == owner
        # Else we have a 404 because 'owner:' is missing from the url.
        if (not owner_in_url) and (user_login != owner):
            assert response.status_code == HTTP_404_NOT_FOUND

        elif should_succeed:
            assert response.status_code == HTTP_200_OK
            returned_feature = json.loads(response.content)
            assert returned_feature["id"] == feature_toto_s1_l1_0.id_
        else:
            assert response.status_code == HTTP_401_UNAUTHORIZED


@AUTH_PARAM
@get_test_cases(
    "POST/DELETE one collection",
    AuthorizationInfo("toto", "new_collection", "write"),
    write_collections=True,
)
async def test_authorization_post_and_delete_one_collection(
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    should_succeed: bool,
):
    """Test the POST and DELETE /catalog/collections/{owner}:{collection_id} endpoints"""

    owner = requested_collections[0].owner_id
    collection_id = requested_collections[0].collection_id
    new_collection = Collection(owner, collection_id)
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # The 'owner:' is needed in the url, except in the 'implicit owner' case (when user == collection owner)
    for owner_in_url in f"{owner}:", "":

        # Create the collection
        post_response = client.request("POST", "/catalog/collections", json=new_collection.properties, **header)

        if should_succeed:
            assert post_response.status_code == HTTP_201_CREATED
            returned_col = json.loads(post_response.content)
            assert returned_col["owner"] == owner
            assert returned_col["id"] == collection_id
        else:
            assert post_response.status_code == HTTP_401_UNAUTHORIZED

        # Delete the collection so we're back to the initial test state.
        # NOTE: it has actually been created only in the should_succeed case.
        delete_response = client.delete(f"/catalog/collections/{owner_in_url}{collection_id}", **header)

        # The implicit owner should work only when user == owner
        # Else we have a 404 because 'owner:' is missing from the url.
        if (not owner_in_url) and (user_login != owner):
            assert delete_response.status_code == HTTP_404_NOT_FOUND

            # Delete the collection with the good url, in case it has been created,
            # or we'll have conflicts in the next tests
            client.delete(f"/catalog/collections/{owner}:{collection_id}", **header)

        elif should_succeed:
            assert delete_response.status_code == HTTP_200_OK
            assert json.loads(delete_response.content) == {"deleted collection": "new_collection"}

        # NOTE: in this case, the collection has not been created.
        # But we still receive a 401 not 404 even though the colleciton does not exist.
        else:
            assert delete_response.status_code == HTTP_401_UNAUTHORIZED


@AUTH_PARAM
@get_test_cases("PUT one collection", AuthorizationInfo("toto", "S1_L1", "write"), write_collections=True)
async def test_authorization_put_one_collection(
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    should_succeed: bool,
):
    """Test the PUT /catalog/collections/{owner}:{collection_id} endpoint (to update a collection)"""

    owner = requested_collections[0].owner_id
    collection_id = requested_collections[0].collection_id
    existing_collection = Collection(owner, collection_id)
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # The 'owner:' is needed in the url, except in the 'implicit owner' case (when user == collection owner)
    for owner_in_url in f"{owner}:", "":

        # Update the collection
        response = client.request(
            "PUT",
            f"/catalog/collections/{owner_in_url}{collection_id}",
            json=existing_collection.properties,
            **header,
        )

        # The implicit owner should work only when user == owner
        # Else we have a 404 because 'owner:' is missing from the url.
        if (not owner_in_url) and (user_login != owner):
            assert response.status_code == HTTP_404_NOT_FOUND

        elif should_succeed:
            assert response.status_code == HTTP_200_OK
            returned_col = json.loads(response.content)
            assert returned_col["owner"] == owner
            assert returned_col["id"] == collection_id
        else:
            assert response.status_code == HTTP_401_UNAUTHORIZED


@AUTH_PARAM
@get_test_cases(
    "GET/POST search",
    [
        AuthorizationInfo("toto", "S1_L1", "read"),
        AuthorizationInfo("toto", "S2_L3", "read"),
    ],
)
@pytest.mark.parametrize("method", ["GET", "POST"], ids=["get", "post"])
async def test_authorization_search(
    request,
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    should_succeed: bool,
    feature_toto_s1_l1_0,
    feature_toto_s1_l1_1,
    feature_toto_s2_l3_0,
    method: str,
):
    """Test the GET and POST /catalog/search endpoints"""
    # Requested collection owner and ids.
    owner = requested_collections[0].owner_id
    single_collection = ["S1_L1"]
    several_collections = ["S1_L1", "S2_L3"]
    header = VALID_APIKEY_HEADER if test_apikey else {}

    def get_search_kwargs(searched_collections: list[str]):
        """Return the arguments to pass to the search request"""
        params: dict[str, Any] = {}
        if method == "GET":
            params = {
                "collections": ",".join(searched_collections),
                "filter-lang": "cql2-text",
                "filter": f"width=2500 AND owner={owner!r}",
            }
            return {"params": params}
        # POST
        params = {
            "collections": searched_collections,
            "filter-lang": "cql2-json",
            "filter": {
                "op": "and",
                "args": [
                    {"op": "=", "args": [{"property": "owner"}, owner]},
                    {"op": "=", "args": [{"property": "width"}, 2500]},
                ],
            },
        }
        return {"json": params}

    # Search a single collection
    response = client.request(method, "/catalog/search", **get_search_kwargs(single_collection), **header)

    if should_succeed:
        assert response.status_code == HTTP_200_OK
        returned_features = json.loads(response.content)["features"]
        assert [feature["id"] for feature in returned_features] == [
            feature_toto_s1_l1_0.id_,
            feature_toto_s1_l1_1.id_,
        ]
    else:
        assert response.status_code == HTTP_401_UNAUTHORIZED

    # Search several collections
    response = client.request(method, "/catalog/search", **get_search_kwargs(several_collections), **header)

    # In this specific case, we search for 2 collections but only have authorization on one collection.
    # The search returns an unauthorized response.
    if "partial_roles" in request.node.name:
        # 'requested_collections' are in fact the authorized collections for the user.
        assert len(requested_collections) < len(several_collections)
        assert response.status_code == HTTP_401_UNAUTHORIZED

    elif should_succeed:
        assert response.status_code == HTTP_200_OK
        returned_features = json.loads(response.content)["features"]
        assert [feature["id"] for feature in returned_features] == [
            feature_toto_s2_l3_0.id_,
            feature_toto_s1_l1_0.id_,
            feature_toto_s1_l1_1.id_,
        ]
    else:
        assert response.status_code == HTTP_401_UNAUTHORIZED


@AUTH_PARAM
@get_test_cases("GET download file", AuthorizationInfo("toto", "S1_L1", "download"))
async def test_authorization_download(
    _init_authorization_test,
    _init_bucket_for_auth_download,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    should_succeed: bool,
    feature_toto_s1_l1_0,
):
    """Test the GET /catalog/collections/{owner}:{collection_id}/items/{item_id}/download/{filename} endpoint"""

    owner = requested_collections[0].owner_id
    collection_id = requested_collections[0].collection_id
    item_id = feature_toto_s1_l1_0.id_
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # The 'owner:' is needed in the url, except in the 'implicit owner' case (when user == collection owner)
    for owner_in_url in f"{owner}:", "":

        response = client.request(
            "GET",
            f"/catalog/collections/{owner_in_url}{collection_id}/items/{item_id}/download/may24C355000e4102500n.tif",
            **header,
        )

        # The implicit owner should work only when user == owner
        # Else we have a 404 because 'owner:' is missing from the url.
        missing_owner_in_url = (not owner_in_url) and (user_login != owner)
        if missing_owner_in_url:
            assert response.status_code == HTTP_404_NOT_FOUND

        elif should_succeed:
            assert response.status_code == HTTP_302_FOUND

            # Check that response is empty
            assert response.content == b""

            # call the redirected url
            product_content = requests.get(response.headers["location"], timeout=10)
            assert product_content.status_code == HTTP_200_OK
            assert product_content.content.decode() == _init_bucket_for_auth_download["object_content"]
        else:
            assert response.status_code == HTTP_401_UNAUTHORIZED

        # test with a non-existing asset id
        response = client.get(
            f"/catalog/collections/{owner_in_url}{collection_id}/items/{item_id}/download/UNKNWON",
            **header,
        )
        if missing_owner_in_url or should_succeed:
            assert response.status_code == HTTP_404_NOT_FOUND
        else:
            assert response.status_code == HTTP_401_UNAUTHORIZED

        response = client.get(
            f"/catalog/collections/{owner_in_url}{collection_id}/items/INCORRECT_ITEM_ID/download/UNKNOWN",
            **header,
        )
        assert response.status_code == HTTP_404_NOT_FOUND  # 404 in all cases


@AUTH_PARAM
@get_test_cases("POST/DELETE one item", AuthorizationInfo("toto", "S1_L1", "write"))
async def test_authorization_post_and_delete_one_item(
    _init_authorization_test,
    _init_bucket_for_auth_download,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    should_succeed: bool,
):
    """
    Test the POST /catalog/collections/{owner}:{collection_id}/items
    and DELETE /catalog/collections/{owner}:{collection_id}/items/{item_id} endpoints
    """
    owner = requested_collections[0].owner_id
    collection_id = requested_collections[0].collection_id
    feature_id = "new_feature"
    new_feature = Feature(owner, feature_id, collection_id)
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # The 'owner:' is needed in the url, except in the 'implicit owner' case (when user == collection owner)
    for owner_in_url in f"{owner}:", "":

        # Upload dummy object before each post and delete
        _init_bucket_for_auth_download["upload_object"]()

        # Create the item
        post_response = client.post(
            f"/catalog/collections/{owner_in_url}{collection_id}/items",
            json=new_feature.properties,
            **header,
        )

        # The implicit owner should work only when user == owner
        # Else we have a 404 because 'owner:' is missing from the url.
        missing_owner_in_url = (not owner_in_url) and (user_login != owner)
        if missing_owner_in_url:
            assert post_response.status_code == HTTP_404_NOT_FOUND

        elif should_succeed:
            assert post_response.status_code == HTTP_201_CREATED
            returned_feature = json.loads(post_response.content)
            assert returned_feature["id"] == feature_id
            assert returned_feature["collection"] == collection_id
        else:
            assert post_response.status_code == HTTP_401_UNAUTHORIZED

        # Delete the item if it has been created, don't change the collection, because it is used by other tests also.
        # NOTE: it has actually been created only in the should_succeed case.
        delete_response = client.request(
            "DELETE",
            f"/catalog/collections/{owner_in_url}{collection_id}/items/{feature_id}",
            json=new_feature.properties,
            **header,
        )
        if missing_owner_in_url:
            assert delete_response.status_code == HTTP_404_NOT_FOUND
        elif should_succeed:
            assert delete_response.status_code == HTTP_200_OK
            assert json.loads(delete_response.content) == {"deleted item": feature_id}
        # NOTE: in this case, the collection has not been created.
        # But we still receive a 401 not 404 even though the colleciton does not exist.
        else:
            assert delete_response.status_code == HTTP_401_UNAUTHORIZED


@AUTH_PARAM
@get_test_cases("PUT one item", AuthorizationInfo("toto", "S1_L1", "write"))
async def test_authorization_put_one_item(
    _init_authorization_test,
    client,
    test_apikey: bool,
    requested_collections: list[AuthorizationInfo],
    user_login: str,
    should_succeed: bool,
    feature_toto_s1_l1_0,
):
    """Test the PUT /catalog/collections/{owner}:{collection_id}/items/{item_id} endpoint (to update an item)"""

    owner = requested_collections[0].owner_id
    collection_id = requested_collections[0].collection_id
    feature_id = feature_toto_s1_l1_0.id_
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # The 'owner:' is needed in the url, except in the 'implicit owner' case (when user == collection owner)
    for owner_in_url in f"{owner}:", "":

        # Update the collection
        response = client.request(
            "PUT",
            f"/catalog/collections/{owner_in_url}{collection_id}/items/{feature_id}",
            json=feature_toto_s1_l1_0.properties,
            **header,
        )

        # The implicit owner should work only when user == owner
        # Else we have a 404 because 'owner:' is missing from the url.
        if (not owner_in_url) and (user_login != owner):
            assert response.status_code == HTTP_404_NOT_FOUND

        elif should_succeed:
            assert response.status_code == HTTP_200_OK
            returned_feature = json.loads(response.content)
            assert returned_feature["id"] == feature_id
            assert returned_feature["collection"] == collection_id
        else:
            assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthentication:
    """Test that the user must be authenticated to access catalog endpoints."""

    @pytest.mark.httpx_mock(can_send_already_matched_responses=True)
    @pytest.mark.parametrize("test_apikey", [True, False], ids=["test_apikey", "no_apikey"])
    @pytest.mark.parametrize("test_oauth2", [True, False], ids=["test_oauth2", "no_oauth2"])
    async def test_error_when_not_authenticated(self, mocker, client, httpx_mock: HTTPXMock, test_apikey, test_oauth2):
        """
        Test that all the http endpoints are protected and return 401 or 403 if not authenticated.
        """
        owner_id = "pyteam"
        await init_authentication_test(
            mocker,
            httpx_mock,
            client,
            test_apikey,
            test_oauth2,
            [],
            {},
            mock_wrong_apikey=True,
            user_login=owner_id,
        )
        header = VALID_APIKEY_HEADER if test_apikey else {}

        # For each route and method from the openapi specification i.e. with the /catalog/ prefixes
        for path, methods in app.openapi()["paths"].items():
            if not must_be_authenticated(path):
                continue
            for method in methods.keys():

                endpoint = path.format(collection_id="collection_id", item_id="item_id", owner_id=owner_id)
                logger.debug(f"Test the {endpoint!r} [{method}] authentication")

                # With a valid apikey or oauth2 authentication, we should have a status code != 401 or 403.
                # We have other errors on many endpoints because we didn't give the right arguments,
                # but it's OK it is not what we are testing here.
                if test_apikey or test_oauth2:
                    response = client.request(method, endpoint, **header)
                    logger.debug(response)
                    assert response.status_code not in (
                        HTTP_401_UNAUTHORIZED,
                        HTTP_403_FORBIDDEN,
                        HTTP_422_UNPROCESSABLE_CONTENT,  # with 422, the authentication is not called and not tested
                    )

                    # With a wrong apikey, we should have a 403 error
                    if test_apikey:
                        assert client.request(method, endpoint, **WRONG_APIKEY_HEADER).status_code == HTTP_403_FORBIDDEN

                # Check that without authentication, the endpoint is protected and we receive a 401
                else:
                    assert client.request(method, endpoint).status_code == HTTP_401_UNAUTHORIZED

    def test_authenticated_endpoints(self):
        """Test that the catalog endpoints need authentication."""
        for route_path in [
            "/catalog/_mgmt/health",
            "/catalog/_mgmt/ping",
            "/catalog/api",
            "/catalog/api.html",
            "/auth/",
        ]:
            assert not must_be_authenticated(route_path)
        for route_path in [
            "/catalog",
            "/catalog/",
            "/catalog/conformance",
            "/catalog/collections",
            "/catalog/search",
            "/catalog/queryables",
        ]:
            assert must_be_authenticated(route_path)
