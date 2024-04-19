"""OpenTelemetry utility"""

import inspect
import os
import pkgutil
import sys

import fastapi
import opentelemetry.instrumentation
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.asyncio import AsyncioInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)


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

    FastAPIInstrumentor.instrument_app(app, tracer_provider=otel_tracer)
    logger.debug(f"OpenTelemetry instrumentation of 'fastapi.FastAPIInstrumentor'")

    # Instrument all the dependencies under opentelemetry.instrumentation.*

    # Don't instrument FastAPI (it has already been instrumented above)
    # or asyncio (it has error, we should see why)
    ignored_classes = (AsyncioInstrumentor, FastAPIInstrumentor)

    package = opentelemetry.instrumentation
    prefix = package.__name__ + "."
    classes = set()

    # Recursively find all package modules
    for _, module_str, _ in pkgutil.walk_packages(path=package.__path__, prefix=prefix, onerror=None):
        try:

            # Import and find all module classes
            __import__(module_str)
            for _, _class in inspect.getmembers(sys.modules[module_str]):
                if inspect.isclass(_class) and (_class not in classes):

                    # Save the class (classes are found several times when imported by other modules)
                    classes.add(_class)

                    if _class in ignored_classes:
                        continue

                    # If the "instrument" method exists
                    _instrument = getattr(_class, "instrument", None)
                    if callable(_instrument):

                        # Call it with the same arguments than FastAPI
                        _class().instrument(tracer_provider=otel_tracer)
                        name = f"{module_str}.{_class.__name__}".removeprefix(prefix)
                        logger.debug(f"OpenTelemetry instrumentation of {name!r}")

        # Ignore exceptions, don't load this module
        except Exception:
            pass
