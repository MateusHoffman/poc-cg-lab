from __future__ import annotations

import contextvars
import time
from collections import deque
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

SPANS: deque[dict] = deque(maxlen=40)
AUDIT: deque[dict] = deque(maxlen=20)
_BUCKET: contextvars.ContextVar[list | None] = contextvars.ContextVar("cg_spans", default=None)
_CONFIGURED = False


class MemorySpanExporter(SpanExporter):
    def export(self, spans) -> SpanExportResult:
        for span in spans:
            SPANS.append(
                {
                    "name": span.name,
                    "trace_id": format(span.context.trace_id, "032x"),
                    "duration_ms": round((span.end_time - span.start_time) / 1_000_000, 2),
                    "attributes": {
                        key: value for key, value in span.attributes.items()
                    },
                }
            )
        return SpanExportResult.SUCCESS


def setup_telemetry() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(MemorySpanExporter()))
    trace.set_tracer_provider(provider)
    _CONFIGURED = True


def tracer():
    setup_telemetry()
    return trace.get_tracer("cg.autoagent")


@contextmanager
def collect_spans():
    bucket: list[dict] = []
    token = _BUCKET.set(bucket)
    try:
        yield bucket
    finally:
        _BUCKET.reset(token)


@contextmanager
def start_span(name: str, **attributes: str | int | float | bool):
    started = time.perf_counter()
    with tracer().start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        item = {
            "name": name,
            "trace_id": format(span.get_span_context().trace_id, "032x"),
            "duration_ms": 0.0,
            "attributes": dict(attributes),
        }
        bucket = _BUCKET.get()
        if bucket is not None:
            bucket.append(item)
        try:
            yield span
        finally:
            item["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)


def recent_spans() -> list[dict]:
    return list(SPANS)


def record_audit(entry: dict) -> None:
    AUDIT.appendleft(entry)


def audit_log() -> list[dict]:
    return list(AUDIT)
