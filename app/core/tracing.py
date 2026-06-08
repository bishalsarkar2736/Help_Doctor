import os

from opentelemetry import trace

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)

from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)

from opentelemetry.instrumentation.fastapi import (
    FastAPIInstrumentor,
)

from opentelemetry.instrumentation.redis import (
    RedisInstrumentor,
)

from opentelemetry.instrumentation.httpx import (
    HTTPXClientInstrumentor,
)

from opentelemetry.trace import (
    get_current_span,
)

from app.core.correlation import (
    correlation_id_ctx,
)


def setup_tracing(app):

    resource = Resource.create({
        "service.name": "helpdoctor-api",
    })

    if os.getenv("TESTING") != "1":
        
        provider = TracerProvider(
            resource=resource,
        )

        processor = BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint="http://localhost:4318/v1/traces"
            )
        )

        provider.add_span_processor(
            processor
        )

        trace.set_tracer_provider(
            provider
        )

        # -----------------------------
        # Auto instrumentation
        # -----------------------------

        FastAPIInstrumentor.instrument_app(
            app
        )

        RedisInstrumentor().instrument()

        HTTPXClientInstrumentor().instrument()


def inject_trace_attributes(
    *,
    user_id: int | None = None,
    appointment_id: int | None = None,
):

    span = get_current_span()

    correlation_id = (
        correlation_id_ctx.get()
    )

    if correlation_id:

        span.set_attribute(
            "correlation_id",
            correlation_id,
        )

    if user_id is not None:

        span.set_attribute(
            "user_id",
            user_id,
        )

    if appointment_id is not None:

        span.set_attribute(
            "appointment_id",
            appointment_id,
        )