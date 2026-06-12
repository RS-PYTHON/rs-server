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

"""Unit tests for OpenTelemetry."""

from contextlib import contextmanager

import pytest
import requests
from opentelemetry.trace.span import NonRecordingSpan, SpanContext, TraceFlags
from rs_server_common.utils.init_opentelemetry import (
    botocore_hook,
    fastapi_hook,
    init_traces,
    parse_data,
    requests_hook,
    start_span,
    trace_requests_body,
    trace_requests_headers,
)


def test_trace_flags_read_environment_variables(monkeypatch):
    """Test trace_requests_headers() and trace_requests_body() read their environment flags."""
    monkeypatch.setenv("OTEL_PYTHON_REQUESTS_TRACE_HEADERS", "true")
    monkeypatch.setenv("OTEL_PYTHON_REQUESTS_TRACE_BODY", "1")

    assert trace_requests_headers() is True
    assert trace_requests_body() is True


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (None, ""),
        (b"plain text", "plain text"),
        ('{"key": "value"}', '{\n  "key": "value"\n}'),
        ({b"key": b"value"}, '{\n  "key": "value"\n}'),
        ([("key", "value")], '{\n  "key": "value"\n}'),
    ],
)
def test_parse_data_formats_supported_payloads(data, expected):
    """Test parse_data() converts headers and bodies to stable strings."""
    assert parse_data(data) == expected


def test_requests_hook_adds_headers_and_body_attributes(mocker, monkeypatch):
    """Test requests_hook() enriches a recording span with request and response data."""
    monkeypatch.setenv("OTEL_PYTHON_REQUESTS_TRACE_HEADERS", "true")
    monkeypatch.setenv("OTEL_PYTHON_REQUESTS_TRACE_BODY", "true")

    span = mocker.Mock()
    span.is_recording.return_value = True
    span.attributes = {"http.url": "https://example.test/data"}
    request = requests.Request(
        "POST",
        "https://example.test/data",
        headers={"X-Test": "yes"},
        data="request-body",
    ).prepare()
    response = requests.Response()
    response.status_code = 200
    response.headers["X-Response"] = "ok"
    # requests_hook() reads response.content, so mark the fake response body as already loaded.
    response._content = b"response-body"  # pylint: disable=protected-access
    setattr(response, "_content_consumed", True)

    requests_hook(span, request, response)

    # The hook sets several span attributes; assert_any_call checks each expected one was included.
    span.set_attribute.assert_any_call("_url", "https://example.test/data")
    span.set_attribute.assert_any_call("http.request.headers", '{\n  "X-Test": "yes",\n  "Content-Length": "12"\n}')
    span.set_attribute.assert_any_call("http.response.headers", '{\n  "X-Response": "ok"\n}')
    span.set_attribute.assert_any_call("http.request.body", "request-body")
    span.set_attribute.assert_any_call("http.response.content", "response-body")


def test_requests_hook_ignores_non_recording_span(mocker):
    """Test requests_hook() returns early when the span is not recording."""
    span = mocker.Mock()
    span.is_recording.return_value = False
    request = requests.Request("GET", "https://example.test").prepare()

    requests_hook(span, request)

    span.set_attribute.assert_not_called()


def test_fastapi_hook_adds_scope_and_message_attributes(mocker, monkeypatch):
    """Test fastapi_hook() enriches a recording span with ASGI scope and message data."""
    monkeypatch.setenv("OTEL_PYTHON_REQUESTS_TRACE_HEADERS", "true")
    monkeypatch.setenv("OTEL_PYTHON_REQUESTS_TRACE_BODY", "true")

    span = mocker.Mock()
    span.is_recording.return_value = True
    # ASGI headers are byte pairs; parse_data() decodes them before attaching span attributes.
    scope = {"path": "/dpr/processes", "headers": [(b"x-test", b"yes")]}
    message = {"headers": [(b"x-message", b"ok")], "body": b"message-body"}

    fastapi_hook(span, scope, message)

    # The ASGI hook enriches the same span with scope data and message payload details.
    span.set_attribute.assert_any_call("_path", "/dpr/processes")
    span.set_attribute.assert_any_call("http.scope.headers", '{\n  "x-test": "yes"\n}')
    span.set_attribute.assert_any_call("http.message.headers", '{\n  "x-message": "ok"\n}')
    span.set_attribute.assert_any_call("http.message.body", "message-body")


def test_botocore_hook(mocker):
    """Test botocore_hook() enriches a recording span with path."""

    span = mocker.Mock()
    span.is_recording.return_value = True
    api_params = {"Bucket": "my_bucket", "Key": "my_key"}

    botocore_hook(span, None, None, api_params)

    # The ASGI hook enriches the same span
    span.set_attribute.assert_any_call("_path", "s3://my_bucket/my_key")


def test_fastapi_hook_ignores_non_recording_span(mocker):
    """Test fastapi_hook() returns early when the span is not recording."""
    span = mocker.Mock()
    span.is_recording.return_value = False

    fastapi_hook(span, {"path": "/dpr/processes"})

    span.set_attribute.assert_not_called()


def test_start_span_creates_root_span(mocker):
    """Test start_span() creates a root span when no parent context is provided."""
    expected_span = mocker.Mock()

    @contextmanager
    def fake_start_as_current_span(name):
        """Yield a fake span from the mocked tracer."""
        assert name == "root-span"
        yield expected_span

    tracer = mocker.Mock()
    tracer.start_as_current_span.side_effect = fake_start_as_current_span
    get_tracer = mocker.patch("rs_server_common.utils.init_opentelemetry.trace.get_tracer", return_value=tracer)

    with start_span("test.module", "root-span") as span:
        assert span is expected_span

    get_tracer.assert_called_once_with("test.module")
    tracer.start_as_current_span.assert_called_once_with("root-span")


def test_start_span_creates_child_span_from_parent_context(mocker):
    """Test start_span() creates a child span when a parent context is provided."""
    expected_span = mocker.Mock()
    parent_context = SpanContext(
        trace_id=1,
        span_id=2,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )

    @contextmanager
    def fake_start_as_current_span(name):
        """Yield a fake child span from the mocked tracer."""
        assert name == "child-span"
        yield expected_span

    @contextmanager
    def fake_use_span(span):
        """Assert the parent span wrapper is used around the child span."""
        assert isinstance(span, NonRecordingSpan)
        assert span.get_span_context().trace_id == parent_context.trace_id
        assert span.get_span_context().span_id == parent_context.span_id
        yield span

    tracer = mocker.Mock()
    tracer.start_as_current_span.side_effect = fake_start_as_current_span
    mocker.patch("rs_server_common.utils.init_opentelemetry.trace.get_tracer", return_value=tracer)
    # Child spans first bind a NonRecordingSpan made from the parent SpanContext.
    use_span = mocker.patch("rs_server_common.utils.init_opentelemetry.trace.use_span", side_effect=fake_use_span)

    with start_span("test.module", "child-span", parent_context) as span:
        assert span is expected_span

    use_span.assert_called_once()
    tracer.start_as_current_span.assert_called_once_with("child-span")


def test_instrumentation(mocker, monkeypatch):
    """
    Call instrumentation code. It's only for the code coverage, don't run additional checks
    on the openlemetry internal code.
    """
    mocker.patch("rs_server_common.utils.init_opentelemetry.initialized", False)
    monkeypatch.setenv("TEMPO_ENDPOINT", "none")

    mocker.patch("rs_server_common.utils.init_opentelemetry.auto_instrumentation")
    mocker.patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app")
    mocker.patch("opentelemetry.instrumentation.instrumentor.BaseInstrumentor.instrument")

    init_traces(app=mocker.Mock(), service_name="pytest")
