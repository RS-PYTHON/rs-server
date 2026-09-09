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

"""Utility functions used by the pytest unit tests."""

import os
from copy import deepcopy
from typing import Any, Literal

import httpx
import responses
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from eodag.plugins.search.qssearch import QueryStringSearch
from fastapi import status
from fastapi.testclient import TestClient
from keycloak import KeycloakAdmin
from rs_server_adgs import adgs_utils
from rs_server_cadip import cadip_utils
from rs_server_common.authentication import oauth2
from rs_server_prip import prip_utils
from starlette.responses import RedirectResponse


async def mock_oauth2(  # pylint: disable=too-many-arguments
    mocker,
    client: TestClient,
    endpoint: str,
    user_id: str,
    username: str,
    iam_roles: list[str],
    user_attributes: dict[str, Any],
    enabled: bool = True,
    assert_success: bool = True,
) -> httpx.Response:
    """
    Only for unit tests: mock the OAuth2 authorization code flow process.

    Args:
        mocker: pytest mocker
        client: pytest client
        endpoint: endpoint to test
        user_id: user id in keycloak
        username: username in keycloak
        iam_roles: user iam roles in keycloak
        user_attributes (dict[str, Any]): Additional Keycloak user attributes to include in the mocked token.
        enabled: is the user enabled in keycloak ?
        assert_success: is the login process expected to success ?
    """

    # Clear the cookies, except for the logout endpoint which does it itself
    logout = endpoint.endswith("/logout")
    if logout:
        assert "session" in dict(client.cookies)  # nosec
    else:
        client.cookies.clear()

    # If we are not loging from the console, we simulate the fact that our request comes from a browser
    login_from_console = endpoint.endswith(oauth2.LOGIN_FROM_CONSOLE)
    headers = {"user-agent": "Mozilla/"}

    # The 1st step of the oauth2 authorization code flow returns a redirection to the keycloak login page.
    # After login, it returns a redirection to the original calling endpoint, but this time
    # with a 'code' and 'state' params.
    # Here we do not test the keycloak login page, we only mock the last redirection.
    mocker.patch.object(
        StarletteOAuth2App,
        "authorize_redirect",
        return_value=RedirectResponse(f"{endpoint}?code=my_code&state=my_state", status_code=302),
    )

    # The 2nd step checks the 'code' and 'state' params then returns a dict which contains the user information
    mocker.patch.object(
        StarletteOAuth2App,
        "authorize_access_token",
        return_value={"userinfo": {"sub": user_id, "preferred_username": username}},
    )

    # Then the service will ask for user information in KeyCloak
    mocker.patch.object(KeycloakAdmin, "get_user", return_value={"enabled": enabled, "attributes": user_attributes})
    mocker.patch.object(
        KeycloakAdmin,
        "get_composite_realm_roles_of_user",
        return_value=[{"name": role} for role in iam_roles],
    )

    # We need the client to follow redirections.
    # Note: even with this, the "login from browser" fails with a 400, I don't know why.
    # Use the "login from console instead".
    old_follow_redirects = client.follow_redirects
    try:
        client.follow_redirects = True

        # Call the endpoint that will run the oauth2 authentication process
        response = client.get(endpoint, headers=headers)

        # From the console, the redirection after the 1st step must be done manually
        if login_from_console:
            assert response.is_success  # nosec
            response = client.get(response.json())

    # Restore the redirections
    finally:
        client.follow_redirects = old_follow_redirects

    if assert_success:
        assert response.is_success, f"{endpoint} => {response}"  # nosec

    # After this, if successful, we should have a cookie with the authentication information.
    # Except for the logout endpoint which should have removed the cookie.
    has_cookie = response.is_success and not logout
    if client.cookies:
        assert ("session" in dict(client.cookies)) == has_cookie  # nosec

    return response


def create_mock_collection(service: Literal["adgs", "cadip", "prip"], col_id: str, configured_query: dict):
    """
    Create a mock collection.

    Args:
        service: adgs, cadip or prip
        col_id: id of the mocked collection
        configured_query: configured query for this collection, i.e. the collection  will only return results
        from this query.
    """
    adgs = service == "adgs"
    cadip = service == "cadip"
    prip = service == "prip"

    # Read a collection from:
    # rs-server/services/adgs/config/adgs_search_config.yaml or
    # rs-server/services/cadip/config/cadip_search_config.yaml or
    # rs-server/services/prip/config/prip_search_config.yaml
    if adgs:
        col_name = "adgs_by_platform"
        service_utils = adgs_utils
    elif cadip:
        col_name = "cadip_session_by_id_list"
        service_utils = cadip_utils
    elif prip:
        col_name = "S1A_L0_IW_RAW"
        service_utils = prip_utils
    else:
        raise NotImplementedError

    collections: dict = service_utils.read_conf()["collections"]
    collection = [col for col in collections if col["id"] == col_name][0]

    # Copy the cached response before we modify it
    collection = deepcopy(collection)

    # Keep everything except the id and hardcoded query
    collection["id"] = col_id
    collection["query"] = configured_query
    return collection


def call_mocked_search(
    # Parameters coming from the pytest
    mocker,
    client,
    service: Literal["adgs", "cadip", "prip"],
    method: Literal["GET", "POST"],
    expected_response: dict,
    cadip_file_response: dict,
    filter_type: Literal["cql", "query"] = "cql",
    # Requested collections
    cols: list[str] | None = None,
    # Platforms and constellations
    request_platforms: list[str] | None = None,
    request_constellations: list[str] | None = None,
    expected_satellites: list[str] | None = None,  # for cadip
    expected_constellations: list[str] | None = None,  # platformShortName, for adgs/prip
    expected_platforms: list[str] | None = None,  # platformSerialIdentifier, for adgs/prip
    # adgs/prip product types
    request_product_types: list[str] | None = None,
    expected_product_types: list[str] | None = None,
    # Datetimes
    request_datetime: str | None = None,  # range as min/max
    expected_publication_date: str | None = None,  # range as min/max
    expected_content_date: str | None = None,  # range as min/max
    # Product or session ids
    ids: list[str] | None = None,
    ids_in_filter: bool = True,  # pass ids inside or outside the filter ?
    # Pagination
    request_sortby: tuple[Literal["-", "+"], str] | None = None,
    request_limit: int | None = None,
    expected_pagination="&$orderby=PublicationDate desc&$top=10&$skip=0",
    # We don't expect any results if the user request does not match the collection config
    expect_result: bool = True,
) -> list[dict]:
    """
    Create a user stac request from parameters.
    Then mock the odata request, that is calculated by rspy from the collection configurations
    and the user request, and is sent to the station.
    Then call the /search and check result.
    """
    adgs = service == "adgs"
    cadip = service == "cadip"
    prip = service == "prip"

    # Spy on eodag.plugins.search.qssearch::QueryStringSearch if it's not already mocked, or reset the mock
    try:
        spy_search = QueryStringSearch.do_search
        spy_search.reset_mock()
    except AttributeError:
        spy_search = mocker.spy(QueryStringSearch, "do_search")

    user_request: dict[str, Any] = {}  # user stac request params, including "filter" or "query"
    user_filters: list[Any] = []  # list of user stac filter/query parts
    odata_filters: dict[str, str] = {}  # list of mocked odata request parts, ordered by key
    odata_kwargs: dict[str, str] = {}  # some odata fields are passed to eodag by kwargs, not url

    def _add_filter(
        request: str,  # "stac" or "odata_xxx"
        key: str,
        values: str | list[str] | None,
        kwargs_key: str = "",
    ):
        """Format a key and values for a stac or odata request"""
        if not values:
            return

        # Field passed by kwargs
        if kwargs_key:
            odata_dict = odata_kwargs
            odata_key = kwargs_key
        # Nominal case: field passed by url
        else:
            odata_dict = odata_filters
            odata_key = key

        if request.startswith("odata_range"):  # datetime range as min/max str
            assert isinstance(values, str)
            date_min = values.split("/", maxsplit=1)[0]
            date_max = values.split("/")[1]
            if request == "odata_range1":
                odata_dict[odata_key] = (
                    f"({key} gt {date_min} or {key} eq {date_min}) and " f"({key} lt {date_max} or {key} eq {date_max})"
                )
            elif request == "odata_range2":
                odata_dict[odata_key] = (
                    f"({key}/Start gt {date_min} or {key}/Start eq {date_min}) and "
                    f"({key}/End lt {date_max} or {key}/End eq {date_max})"
                )
            return

        # Convert single value to list
        if not isinstance(values, list):
            values = [values]

        if request == "odata2":
            odata_dict[odata_key] = " or ".join(f"contains({key},'{v}')" for v in values)
            return

        joined = ""
        if len(values) == 1:
            if request == "stac":
                joined = f"='{values[0]}'"
            elif request == "odata":
                joined = f" eq '{values[0]}'"
        else:
            if (request == "stac") and (filter_type == "query"):
                raise NotImplementedError
            joined = " in (" + ",".join([f"'{v}'" for v in values]) + ")"

        if request == "stac":
            if method == "GET":
                if filter_type == "cql":
                    user_filters.append(f"{key}{joined}")
                else:  # query
                    user_filters.append(f'"{key}": {{"eq": "{values[0]}"}}')
            else:  # POST
                if filter_type == "cql":
                    if len(values) == 1:
                        user_filters.append({"args": [{"property": key}, values[0]], "op": "="})
                    else:
                        user_filters.append({"args": [{"property": key}, values], "op": "in"})
                else:  # query
                    user_filters.append([key, {"eq": values[0]}])
        else:  # odata
            if cadip:
                odata_dict[odata_key] = f"{key}{joined}"
            else:  # adgs/prip
                odata_dict[odata_key] = (
                    f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq '{key}' and "
                    f"att/OData.CSC.StringAttribute/Value{joined})"
                )

    #
    # Handle all parameters

    if ids_in_filter:
        _add_filter("stac", "id", ids)
    if cadip:
        _add_filter("odata", "SessionId", ids)
    elif adgs:
        _add_filter("odata2", "Name", ids)
    elif prip:
        _add_filter("odata2", "Name", ids, kwargs_key="NameContains")

    _add_filter("stac", "platform", request_platforms)
    _add_filter("stac", "constellation", request_constellations)

    _add_filter("odata", "Satellite", expected_satellites)
    _add_filter("odata", "platformSerialIdentifier", expected_platforms)
    _add_filter("odata", "platformShortName", expected_constellations)

    _add_filter("stac", "product:type", request_product_types)
    _add_filter("odata", "productType", expected_product_types)

    _add_filter("odata_range1", "PublicationDate", expected_publication_date)
    _add_filter("odata_range2", "ContentDate", expected_content_date)

    #
    # Non-filter parameters

    if ids and (not ids_in_filter):
        user_request["ids"] = ids if (method == "POST") else ",".join(ids)

    if request_datetime is not None:
        user_request["datetime"] = request_datetime

    if request_limit is not None:
        user_request["limit"] = request_limit

    if request_sortby is not None:
        match request_sortby[1]:
            case "datetime":
                sortby_name = "published" if cadip else "created"
            case _:
                raise NotImplementedError

        sortby_sign = request_sortby[0]
        if method == "GET":
            user_request["sortby"] = f"{sortby_sign}{sortby_name}"
        else:  # POST
            user_request["sortby"] = [{"direction": "desc" if (sortby_sign == "-") else "asc", "field": sortby_name}]

    # Build the user request
    if method == "GET":
        if cols:
            user_request["collections"] = ",".join(cols)
        if user_filters:
            if filter_type == "cql":
                user_request["filter"] = " and ".join(user_filters)
            else:  # query
                user_request["query"] = "{" + ",".join(user_filters) + "}"
    else:  # POST
        if cols:
            user_request["collections"] = cols
        if user_filters:
            if filter_type == "cql":
                user_request["filter"] = {"args": user_filters, "op": "and"}
            else:  # query
                user_request["query"] = dict(user_filters)

    # The mocked odata request fields must respect a certain order
    order_odata_by = []
    if cadip:
        order_odata_by = ["PublicationDate", "SessionId", "Satellite"]
    elif adgs:
        order_odata_by = [
            "PublicationDate",
            "ContentDate",
            "productType",
            "platformSerialIdentifier",
            "platformShortName",
            "Name",
        ]
    elif prip:
        order_odata_by = [
            "PublicationDate",
            "ContentDate",
            "productType",
            "platformShortName",
            "platformSerialIdentifier",
            "Name",
        ]
    ordered_odata = dict(sorted(odata_filters.items(), key=lambda item: order_odata_by.index(item[0]))).values()

    # Build the mocked odata
    odata = "http://127.0.0.1:5000/" + ("Sessions" if cadip else "Products") + "?"
    if odata_filters:
        odata += "$filter=" + " and ".join(ordered_odata)
    odata += expected_pagination
    odata += "&$expand=Attributes" if not cadip else ""

    # Handle some specific cases
    odata = odata.replace("?&$orderby", "?$orderby")

    # Mock the station response
    with responses.RequestsMock() as rsps:
        if expect_result:
            rsps.add(
                responses.GET,
                odata,
                status=status.HTTP_200_OK,
                json=expected_response,
            )
            if cadip:
                odata_query_files = (
                    "http://127.0.0.1:5000/Files?$filter=SessionId eq 'S1A_20200105072204051312'&$top=1000&$skip=0"
                )
                rsps.add(
                    responses.GET,
                    odata_query_files,
                    status=status.HTTP_200_OK,
                    json=cadip_file_response,
                )

        # Call the endpoint
        url = f"{os.getenv('router_prefix')}/search"
        if method == "GET":
            response = client.get(url, params=user_request)
        elif method == "POST":
            response = client.post(url, json=user_request)
        else:
            raise NotImplementedError

        # Check that the odata url and kwargs are the same as expected
        if expect_result:
            assert spy_search.call_args_list[0][0][1].search_urls[0] == odata
            for key, value in odata_kwargs.items():
                assert spy_search.call_args_list[0][1][key] == value

        # Check success and return features
        assert response.is_success
        features = response.json()["features"]

        if expect_result:
            if cadip:
                # 2 calls, one for sessions, one for files
                assert spy_search.call_count == 2
                assert len(spy_search.spy_return) == 2 * len(features) == 2 * len(expected_response["value"])
            else:
                # 1 single call for files
                assert spy_search.call_count == 1
                assert len(spy_search.spy_return) == len(features) == len(expected_response["value"])
        else:
            assert spy_search.call_count == 0
        return features
