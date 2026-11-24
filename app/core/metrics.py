"""Prometheus HTTP metrics instrumentation for the FastAPI application.

Each application instance created by ``create_app()`` receives its own
``CollectorRegistry`` (stored on ``app.state.metrics_registry``) so there is
no shared mutable global state across independent app instances or tests.
"""

from typing import Final

from fastapi import FastAPI
from prometheus_client import CollectorRegistry
from prometheus_fastapi_instrumentator import Instrumentator

# Internal scrape endpoint (kept out of OpenAPI docs and excluded from HTTP
# request counters so Prometheus scrapes do not pollute application metrics).
METRICS_ENDPOINT: Final[str] = "/metrics"


def configure_metrics(app: FastAPI) -> CollectorRegistry:
    """Instrument ``app`` with Prometheus HTTP metrics and expose ``/metrics``.

    Must be called before adding ``SecurityHeadersMiddleware`` so the security
    headers remain the outermost ASGI middleware on every response, including
    ``/metrics``.
    """
    registry = CollectorRegistry()
    # should_instrument_requests_inprogress stays False: upstream 8.1.0 creates
    # that Gauge on the global REGISTRY instead of the custom registry, which
    # breaks per-app isolation in create_app() (ARQ-01).
    instrumentator = Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=False,
        should_group_untemplated=True,
        should_instrument_requests_inprogress=False,
        excluded_handlers=[METRICS_ENDPOINT],
        registry=registry,
    )
    instrumentator.instrument(app).expose(
        app,
        endpoint=METRICS_ENDPOINT,
        include_in_schema=False,
    )
    app.state.metrics_registry = registry
    return registry
