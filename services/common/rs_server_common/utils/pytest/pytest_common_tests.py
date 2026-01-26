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

"""Implement tests that are common to several services."""

import json
from collections.abc import Callable

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from rs_server_common import middlewares
from rs_server_common.middlewares import (
    HandleExceptionsMiddleware,
    Rfc7807ErrorResponse,
    StacErrorResponse,
)
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

rfc7807_response = HandleExceptionsMiddleware.rfc7807_response


# pylint: disable=too-many-branches, too-many-statements, cell-var-from-loop
def test_handle_exceptions_middleware(client, mocker, rfc7807: bool = False):
    """
    Test that HandleExceptionsMiddleware handles and logs errors as expected.

    Args:
        rfc7807 (bool): If true, the returned content is compliant with RFC 7807. This is used by pygeoapi/ogc services.
        False by default = compliant to Stac specifications.
    """

    app = client.app

    # Spy calls to logger.error(...)
    spy_log_error = mocker.spy(middlewares.logger, "error")

    def test_case(
        mocked_endpoint: Callable,
        expected_status: int,
        expected_content: StacErrorResponse | Rfc7807ErrorResponse,
        raise_from_func: bool,
        raise_from_dependency: bool,
    ):
        """
        Test cases.

        Args:
            mocked_endpoint: mocked endpoint implementation. It should return an error or raise an exception.
            expected_status: expected http response status code
            expected_content: expected http response content
            raise_from_func: will the endpoint raise an exception ?
            raise_from_dependency: will the endpoint dependency raise an exception ?
        """

        # Implement a new endpoint that will call our mock
        endpoint_path = "/test_endpoint"

        # Raise exception from the endpoint dependency
        if raise_from_dependency:

            @app.get(endpoint_path)
            def test_endpoint_func(_param=Depends(mocked_endpoint)):
                return "ok"

        # Other cases
        else:

            @app.get(endpoint_path)
            def test_endpoint_func():
                return mocked_endpoint()

        # Call the endpoint
        response = client.get(endpoint_path)

        # Check the expected http response
        assert response.status_code == expected_status  # int status
        # {"code": "xxx", "description": yyy"} or {"type": "xxx", status: yyy, "detail": "zzz"}
        assert response.json() == expected_content

        # Check that logger.error was called once
        spy_log_error.assert_called_once()
        logged_message = spy_log_error.call_args[0][0]

        if raise_from_func or raise_from_dependency:
            # If an exception was raised, then the log was called with the stack trace (exc_info=True arg)
            assert spy_log_error.call_args[1]["exc_info"] is True

            # The logged stack trace should contain either
            # HTTPException(status_code=<expected_status>, detail=<expected_content>)
            # or <ErrorType>(<expected_content>)
            if rfc7807:
                assert expected_content["detail"] in str(logged_message)
            else:
                assert expected_content["description"] in str(logged_message)

        # If no exception, we should have logged the str: '<status>: <message>'
        else:
            assert str(expected_status) in logged_message
            assert json.dumps(expected_content) in logged_message

        # Reset the spy
        spy_log_error.reset_mock()

        # Remove the mocked endpoint
        app.router.routes = list(filter(lambda route: route.path != endpoint_path, app.router.routes))

    ###############
    # Test case 1 #
    ###############

    content = "message from return_error_1"
    if rfc7807:
        error_response = rfc7807_response(status.HTTP_418_IM_A_TEAPOT, detail=content)
    else:
        error_response = StacErrorResponse(code="I'MATeapot", description=content)

    def return_error_1():
        """Test case when the endpoint returns a JSONResponse with a dict content == the expected ErrorResponse"""
        return JSONResponse(status_code=status.HTTP_418_IM_A_TEAPOT, content=error_response)

    test_case(
        mocked_endpoint=return_error_1,
        expected_status=status.HTTP_418_IM_A_TEAPOT,
        expected_content=error_response,
        raise_from_func=False,
        raise_from_dependency=False,
    )

    ###############
    # Test case 2 #
    ###############

    dict_content = {"custom field": "message from return_error_2"}
    if rfc7807:
        expected_content = rfc7807_response(status.HTTP_418_IM_A_TEAPOT, detail=json.dumps(dict_content))
    else:
        expected_content = StacErrorResponse(code="I'MATeapot", description=json.dumps(dict_content))

    def return_error_2():
        """Test case when the endpoint returns a JSONResponse with a dict content != StacErrorResponse"""
        return JSONResponse(status_code=status.HTTP_418_IM_A_TEAPOT, content=dict_content)

    test_case(
        mocked_endpoint=return_error_2,
        expected_status=status.HTTP_418_IM_A_TEAPOT,
        # The returned error content is formated by HandleExceptionsMiddleware
        expected_content=expected_content,
        raise_from_func=False,
        raise_from_dependency=False,
    )

    ###############
    # Test case 3 #
    ###############

    content = "message from return_error_3"
    if rfc7807:
        expected_content = rfc7807_response(status.HTTP_418_IM_A_TEAPOT, detail=content)
    else:
        expected_content = StacErrorResponse(code="I'MATeapot", description=content)

    def return_error_3():
        """Test case when the endpoint returns a JSONResponse with a string content"""
        return JSONResponse(status_code=status.HTTP_418_IM_A_TEAPOT, content=content)

    test_case(
        mocked_endpoint=return_error_3,
        expected_status=status.HTTP_418_IM_A_TEAPOT,
        # The returned error content is formated by HandleExceptionsMiddleware
        expected_content=expected_content,
        raise_from_func=False,
        raise_from_dependency=False,
    )

    ###############
    # Test case 4 #
    ###############

    content = "message from raise_http"
    if rfc7807:
        expected_content = rfc7807_response(status.HTTP_418_IM_A_TEAPOT, detail=content)
    else:
        expected_content = StacErrorResponse(code="I'MATeapot", description=content)

    for exception_type in HTTPException, StarletteHTTPException:

        def raise_http():
            """Test case when the endpoint or dependency raises an HTTPException or StarletteHTTPException"""
            raise exception_type(status.HTTP_418_IM_A_TEAPOT, content)

        for raise_case in True, False:  # raise from either endpoint or dependency
            test_case(
                mocked_endpoint=raise_http,
                expected_status=status.HTTP_418_IM_A_TEAPOT,
                expected_content=expected_content,
                raise_from_func=raise_case,
                raise_from_dependency=not raise_case,
            )

    ###############
    # Test case 5 #
    ###############

    content = "message from raise_value_error"
    if rfc7807:
        expected_content = rfc7807_response(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=content)
    else:
        expected_content = StacErrorResponse(code="ValueError", description=content)

    def raise_value_error():
        """Test case when the endpoint or dependency raises any Exception different than HTTPException"""
        raise ValueError(content)

    for raise_case in True, False:  # raise from either endpoint or dependency
        test_case(
            mocked_endpoint=raise_value_error,
            expected_status=status.HTTP_500_INTERNAL_SERVER_ERROR,  # a generic 500 server-side error is logged
            expected_content=expected_content,
            raise_from_func=raise_case,
            raise_from_dependency=not raise_case,
        )

    # The server can override the HandleExceptionsMiddleware.is_bad_request function
    # that determines if a generic 400 client-side error is logged instead of 500
    old_bad_request = HandleExceptionsMiddleware.is_bad_request
    try:
        HandleExceptionsMiddleware.is_bad_request = lambda *_, **__: True  # always log 400

        if rfc7807:
            expected_content = rfc7807_response(status.HTTP_400_BAD_REQUEST, detail=content)

        for raise_case in True, False:  # raise from either endpoint or dependency
            test_case(
                mocked_endpoint=raise_value_error,
                expected_status=status.HTTP_400_BAD_REQUEST,
                expected_content=expected_content,
                raise_from_func=raise_case,
                raise_from_dependency=not raise_case,
            )

    # Restore old function
    finally:
        HandleExceptionsMiddleware.is_bad_request = old_bad_request
