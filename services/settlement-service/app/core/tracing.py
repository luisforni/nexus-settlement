from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.baggage.propagation import W3CBaggagePropagator

_log = logging.getLogger(__name__)

def setup_tracing() -> None:

    service_name = os.getenv("OTEL_SERVICE_NAME", "settlement-service")
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")

    resource = Resource(attributes={"service.name": service_name, "service.version": "1.0.0"})
    exporter = OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )

    HTTPXClientInstrumentor().instrument()

    SQLAlchemyInstrumentor().instrument()

    _log.info("OpenTelemetry tracing initialised for %s → %s", service_name, otlp_endpoint)

def instrument_app(app: object) -> None:

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="api/v1/health,metrics",
    )
