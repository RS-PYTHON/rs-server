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

"""OpenTelemetry utility"""

import json
import os
from collections.abc import Iterator
from threading import Lock
from typing import Any

import fastapi
import requests
from opentelemetry import trace
from opentelemetry.instrumentation import auto_instrumentation
from opentelemetry.instrumentation.botocore import (
    AiobotocoreInstrumentor,
    BotocoreInstrumentor,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.trace.span import NonRecordingSpan, Span, SpanContext, TraceFlags
from opentelemetry.util._decorator import _agnosticcontextmanager
from rs_server_common.settings import env_bool

lock = Lock()
INITIALIZED = False


# Show details of http headers and body/content in tempo/grafana ?
# Don't store results in global variables because the env var values can change
# after this module was loaded.
def trace_requests_headers():
    """Trace request headers ?"""
    return env_bool("OTEL_PYTHON_REQUESTS_TRACE_HEADERS", default=False)


def trace_requests_body():
    """Trace request bodies and response contents ?"""
    return env_bool("OTEL_PYTHON_REQUESTS_TRACE_BODY", default=False)


def decode(binary_value):
    """Try to decode binary value"""
    try:
        if isinstance(binary_value, bytes):
            return binary_value.decode("utf-8")
    except UnicodeDecodeError:
        pass
    return binary_value


def parse_data(data) -> str:
    """Convert data to a string representation"""

    if not data:
        return ""

    # Try to decode bytes
    if isinstance(data, bytes):
        data = data.decode("utf-8")

    # Try to convert to a dict
    try:
        data = dict(data)
    except Exception:  # pylint: disable=broad-exception-caught # nosec
        pass

    # Or to parse to a dict
    try:
        data = json.loads(data)
    except Exception:  # pylint: disable=broad-exception-caught # nosec
        pass

    # If we have a dict
    if isinstance(data, dict):

        # Decode bytes
        data = {decode(key): decode(value) for key, value in data.items()}

        # Convert to strings
        data = {str(key): str(value) for key, value in data.items()}

        # Apply json formatting
        data = json.dumps(data, indent=2)

    return data or ""


def requests_hook(span: Span, request: requests.PreparedRequest, response: requests.Response | None = None):
    """
    Callback function invoked by RequestsInstrumentor. It implements the hooks:

      - request_hook: invoked right after a span is created.
      - response_hook: invoked right before the span has finished processing a response.

    See: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/requests/requests.html
    """
    if not (span and span.is_recording()):
        return

    # Copy this attribute by adding a '_' prefix to the name,
    # so it appears at the top in the grafana UI, it's more readable
    span.set_attribute("_url", span.attributes.get("http.url"))  # type: ignore

    if trace_requests_headers():
        span.set_attribute("http.request.headers", parse_data(request.headers))
        if response:
            span.set_attribute("http.response.headers", parse_data(response.headers))

    if trace_requests_body():
        span.set_attribute("http.request.body", parse_data(request.body))
        if response:
            span.set_attribute("http.response.content", parse_data(response.content))


def fastapi_hook(span: Span, scope: dict[str, Any], message=None):
    """
    Callback function invoked by FastAPIInstrumentor. It implements the hooks:

      - server_request_hook: called with the server span and ASGI scope object for every incoming request.
      - client_request_hook: called with the internal span, and ASGI scope and event which are sent as dictionaries
                             for when the method receive is called.
      - client_response_hook: called with the internal span, and ASGI scope and event which are sent as dictionaries
                              for when the method send is called.

    See: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html
    """
    if not (span and span.is_recording()):
        return

    # Copy this attribute by adding a '_' prefix to the name,
    # so it appears at the top in the grafana UI, it's more readable
    span.set_attribute("_path", str(scope.get("path")))

    if trace_requests_headers():
        span.set_attribute("http.scope.headers", parse_data(scope.get("headers")))
        if message:
            span.set_attribute("http.message.headers", parse_data(message.get("headers")))

    if trace_requests_body() and message:
        span.set_attribute("http.message.body", parse_data(message.get("body")))


def botocore_hook(span, _service_name, _operation_name, api_params: dict):
    """Callback function invoked by BotocoreInstrumentor and AiobotocoreInstrumentor"""
    if not (span and span.is_recording()):
        return
    bucket = api_params.get("Bucket", "")
    key = api_params.get("Key", "")
    span.set_attribute("_path", f"s3://{bucket}/{key}")


def init_traces(app: fastapi.FastAPI | None, service_name: str):
    """
    Init instrumentation of OpenTelemetry traces.

    Args:
        app (fastapi.FastAPI): FastAPI application
        service_name (str): service name
    """
    with lock:
        global INITIALIZED  # pylint: disable=global-statement
        if INITIALIZED:
            return
        INITIALIZED = True

    # Set the opentelemetry service name
    os.environ["OTEL_SERVICE_NAME"] = service_name

    # Send openelemetry signals to tempo
    if not (tempo_endpoint := os.getenv("TEMPO_ENDPOINT")):
        return
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = tempo_endpoint

    # We'll use custom instrumentation for these packages (separated by ,)
    org_disabled = os.getenv("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS", "")
    os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = f"{org_disabled},aiobotocore,botocore,fastapi,requests"

    # Run the opentelemetry auto instrumentation on all packages under opentelemetry.instrumentation.*
    # This is what the command line "opentelemetry-instrumentation" would do.
    # NOTE: we need 'poetry run opentelemetry-bootstrap -a install' to install these packages.
    try:
        auto_instrumentation.initialize()
    finally:
        os.environ["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] = org_disabled

    #
    # Specific opentelemetry instrumentation with custom hooks
    #

    if app:
        FastAPIInstrumentor.instrument_app(
            app,
            server_request_hook=fastapi_hook,
            client_request_hook=fastapi_hook,
            client_response_hook=fastapi_hook,
        )

    AiobotocoreInstrumentor().instrument(request_hook=botocore_hook)
    BotocoreInstrumentor().instrument(request_hook=botocore_hook)
    RequestsInstrumentor().instrument(request_hook=requests_hook, response_hook=requests_hook)


@_agnosticcontextmanager
def start_span(
    instrumenting_module_name: str,
    name: str,
    span_context: SpanContext | None = None,
) -> Iterator[Span]:
    """
    Context manager for creating a new main or child OpenTelemetry span and set it
    as the current span in this tracer's context.

    Args:
        instrumenting_module_name: Caller module name, just pass __name__
        name: The name of the span to be created (use a custom name)
        span_context: Parent span context. Only to create a child span.

    Yields:
        The newly-created span.
    """
    tracer = trace.get_tracer(instrumenting_module_name)

    # Create a main span
    if not span_context:
        with tracer.start_as_current_span(name) as span:
            yield span

    # Create a child span
    else:
        main_span_context = SpanContext(
            trace_id=span_context.trace_id,
            span_id=span_context.span_id,
            is_remote=True,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        main_span = NonRecordingSpan(main_span_context)
        with trace.use_span(main_span):  # pylint: disable=not-context-manager
            # Optionnaly, we could use the main span instead of creating
            # a new one, to be discussed.
            with tracer.start_as_current_span(name) as span:
                yield span
