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

"""Unit tests for utils module."""

from collections.abc import Callable

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from rs_server_common import middlewares
from rs_server_common.middlewares import HandleExceptionsMiddleware
from starlette import status


def test_handle_exceptions_middleware(fastapi_app, client, mocker):
    """Test that HandleExceptionsMiddleware logs errors as expected."""

    # Spy calls to logger.error(...)
    spy_log_error = mocker.spy(middlewares.logger, "error")

    def test_case(
        mocked_endpoint: Callable,
        expected_status: int,
        expected_content: str | dict,
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

            @fastapi_app.get(endpoint_path)
            def test_endpoint_func(_param=Depends(mocked_endpoint)):
                return "ok"

        # Other cases
        else:

            @fastapi_app.get(endpoint_path)
            def test_endpoint_func():
                return mocked_endpoint()

        # Call the endpoint
        response = client.get(endpoint_path)

        # Check the expected http response
        assert response.status_code == expected_status  # int status
        assert response.json() == expected_content  # {"code": "xxx", "description": yyy"}

        # Check that logger.error was called once
        spy_log_error.assert_called_once()
        logged_message = spy_log_error.call_args[0][0]

        if raise_from_func or raise_from_dependency:
            # If an exception was raised, then the log was called with the stack trace (exc_info=True arg)
            assert spy_log_error.call_args[1]["exc_info"] == True

            # The logged stack trace should contain either
            # HTTPException(status_code=<expected_status>, detail=<expected_content>)
            # or <ErrorType>(<expected_content>)
            assert expected_content["description"] in str(logged_message)

        # If no exception, we should have logged the str: '<status>: <message>'
        else:
            assert str(expected_status) in logged_message
            assert expected_content in logged_message

        # Reset the spy
        spy_log_error.reset_mock()

        # Remove the mocked endpoint
        fastapi_app.router.routes = list(filter(lambda route: route.path != endpoint_path, fastapi_app.router.routes))

    def return_error():
        """Test case when the endpoint returns a JSONResponse"""
        return JSONResponse(status_code=status.HTTP_418_IM_A_TEAPOT, content="json response error message")

    test_case(
        mocked_endpoint=return_error,
        expected_status=status.HTTP_418_IM_A_TEAPOT,
        expected_content="json response error message",
        raise_from_func=False,
        raise_from_dependency=False,
    )

    def raise_http():
        """Test case when the endpoint or dependency raises an HTTPException"""
        raise HTTPException(status.HTTP_418_IM_A_TEAPOT, "http error message")

    for raise_case in True, False:  # raise from either endpoint or dependency
        test_case(
            mocked_endpoint=raise_http,
            expected_status=status.HTTP_418_IM_A_TEAPOT,
            expected_content={"code": "I'MATeapot", "description": "http error message"},
            raise_from_func=raise_case,
            raise_from_dependency=not raise_case,
        )

    def raise_value_error():
        """Test case when the endpoint or dependency raises any Exception different than HTTPException"""
        raise ValueError("value error message")

    for raise_case in True, False:  # raise from either endpoint or dependency
        test_case(
            mocked_endpoint=raise_value_error,
            expected_status=status.HTTP_500_INTERNAL_SERVER_ERROR,  # a generic 500 server-side error is logged
            expected_content={"code": "ValueError", "description": "value error message"},
            raise_from_func=raise_case,
            raise_from_dependency=not raise_case,
        )

    # The server can override the HandleExceptionsMiddleware.is_bad_request function
    # that determines if a generic 400 client-side error is logged instead of 500
    old_bad_request = HandleExceptionsMiddleware.is_bad_request
    try:
        HandleExceptionsMiddleware.is_bad_request = lambda *_, **__: True  # always log 400

        for raise_case in True, False:  # raise from either endpoint or dependency
            test_case(
                mocked_endpoint=raise_value_error,
                expected_status=status.HTTP_400_BAD_REQUEST,
                expected_content={"code": "ValueError", "description": "value error message"},
                raise_from_func=raise_case,
                raise_from_dependency=not raise_case,
            )

    # Restore old function
    finally:
        HandleExceptionsMiddleware.is_bad_request = old_bad_request
