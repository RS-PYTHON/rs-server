"""OpenTelemetry utility"""

import os

import fastapi
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def for_fastapi(app: fastapi.FastAPI, service_name: str):
    """
    OpenTelemetry configuration for FastAPI.

    Args:
        app (fastapi.FastAPI): FastAPI application
        service_name (str): service name
    """

    # See: https://github.com/softwarebloat/python-tracing-demo/tree/main

    otel_resource = Resource(attributes={"service.name": service_name})
    otel_tracer = TracerProvider(resource=otel_resource)
    trace.set_tracer_provider(otel_tracer)
    otel_tracer.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=os.getenv("TEMPO_ENDPOINT"))))

    LoggingInstrumentor().instrument()
    FastAPIInstrumentor.instrument_app(app, tracer_provider=otel_tracer)
