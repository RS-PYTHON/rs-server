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

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from rs_server_common import middlewares
from rs_server_common.middlewares import HandleExceptionsMiddleware
from starlette import status


def test_handle_exceptions_middleware(client, mocker):
    """Test that HandleExceptionsMiddleware logs errors as expected."""

    # Spy calls to logger.error(...)
    spy_log_error = mocker.spy(middlewares.logger, "error")

    def test_case(mocked_service: Callable, should_raise: bool, expected_status: int, expected_content: str | dict):
        """
        Test cases.

        Args:
            mocked_service: how to mock the main function from the tested service
            should_raise: will this mocked function raise an exception ?
            expected_status: expected http response status code
            expected_content: expected http response content
        """
        # Mock the main function from the tested service
        mocker.patch("rs_server_common.fastapi_app.HealthSchema", mocked_service)

        # Call the service with any endpoint
        response = client.get("health")

        # Check the expected http response
        assert response.status_code == expected_status
        assert response.json() == expected_content

        # Check that logger.error was called once
        spy_log_error.assert_called_once()
        logged_content = spy_log_error.call_args[0][0]  # logged message

        if should_raise:
            # If an exception was raised, then the log was called with the stack trace (exc_info=True arg)
            assert spy_log_error.call_args[1]["exc_info"] == True

            # We should have logged either HTTPException(status_code=<expected_status>, detail=<expected_content>)
            # Or <ErrorType>(<expected_content>)
            assert expected_content["description"] in str(logged_content)

        # If no exception, we should have logged the str: '<status>: <message>'
        else:
            assert str(expected_status) in logged_content
            assert expected_content in logged_content

        # Reset the spy
        spy_log_error.reset_mock()

    def return_error(*_, **__):
        """Test case when the service returns a JSONResponse"""
        return JSONResponse(status_code=status.HTTP_418_IM_A_TEAPOT, content="json response error message")

    test_case(
        mocked_service=return_error,
        should_raise=False,
        expected_status=status.HTTP_418_IM_A_TEAPOT,
        expected_content="json response error message",
    )

    def raise_http(*_, **__):
        """Test case when the service raises an HTTPException"""
        raise HTTPException(status.HTTP_418_IM_A_TEAPOT, "http error message")

    test_case(
        mocked_service=raise_http,
        should_raise=True,
        expected_status=status.HTTP_418_IM_A_TEAPOT,
        expected_content={"code": "I'MATeapot", "description": "http error message"},
    )

    def raise_value_error(*_, **__):
        """Test case when the service raises any Exception different than HTTPException"""
        raise ValueError("value error message")

    test_case(
        mocked_service=raise_value_error,
        should_raise=True,
        expected_status=status.HTTP_500_INTERNAL_SERVER_ERROR,  # a generic 500 server-side error is logged
        expected_content={"code": "ValueError", "description": "value error message"},
    )

    # The server can override the HandleExceptionsMiddleware.is_bad_request function
    # that determines if a generic 400 client-side error is logged instead of 500
    old_bad_request = HandleExceptionsMiddleware.is_bad_request
    try:
        HandleExceptionsMiddleware.is_bad_request = lambda *_, **__: True  # always log 400

        test_case(
            mocked_service=raise_value_error,
            should_raise=True,
            expected_status=status.HTTP_400_BAD_REQUEST,
            expected_content={"code": "ValueError", "description": "value error message"},
        )

    # Restore old function
    finally:
        HandleExceptionsMiddleware.is_bad_request = old_bad_request
