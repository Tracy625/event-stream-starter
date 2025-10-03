import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter
from starlette.responses import Response

import api  # noqa: F401 ensure package init instrumentation runs
from api import routes_expert_onchain
from api.config.hotreload import get_registry
from api.core.metrics_store import log_json, set_trace_context
# Import all route modules at the top
from api.routes import (cards, cards_send, dex, health, ingest_x, metrics,
                        onchain, rules, security)
from api.routes import sentiment as sentiment_routes  # sentiment routes shim
from api.routes import signals_heat, signals_summary, signals_topic, x_health

# HTTP metrics
try:
    from api.core.metrics import PROM_REGISTRY

    http_requests_total = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status_code"],
        registry=PROM_REGISTRY,
    )
    http_request_duration_seconds = Counter(
        "http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "endpoint"],
        registry=PROM_REGISTRY,
    )
except ImportError:
    # Fallback to no-op metrics
    class NoOpMetric:
        def labels(self, **kwargs):
            return self

        def inc(self, amount=1):
            pass

        def observe(self, value):
            pass

    http_requests_total = NoOpMetric()
    http_request_duration_seconds = NoOpMetric()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup: Initialize hot reload registry
    try:
        registry = get_registry()
        log_json(
            stage="config.startup",
            version=registry.snapshot_version(),
            enabled=registry._enabled,
            message="[hotreload] Configuration registry initialized",
        )
    except Exception as e:
        log_json(
            stage="config.startup.error",
            error=str(e),
            message="[hotreload] Failed to initialize configuration registry",
        )
        # Fail-fast: exit if configuration cannot be loaded at startup
        import sys

        sys.exit(1)

    yield

    # Shutdown: Nothing to do for now


app = FastAPI(title="GUIDS API", lifespan=lifespan)


# Add tracing middleware (replaces TraceMiddleware)
@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    # Generate IDs
    trace_id = uuid.uuid4().hex[:16]
    request_id = uuid.uuid4().hex[:8]

    # Set context for this request
    set_trace_context(trace_id, request_id)

    # Add IDs to request state for downstream use
    request.state.trace_id = trace_id
    request.state.request_id = request_id

    # Log request start
    start_time = time.time()
    log_json(
        "http.request.start",
        method=str(request.method),
        path=str(request.url.path),
        query=str(request.url.query) if request.url.query else None,
    )

    try:
        response = await call_next(request)

        # Log request end
        duration_ms = int((time.time() - start_time) * 1000)
        log_json(
            "http.request.end",
            method=str(request.method),
            path=str(request.url.path),
            status=response.status_code,
            duration_ms=duration_ms,
        )

        # Update metrics
        endpoint = str(request.url.path)
        http_requests_total.labels(
            method=str(request.method),
            endpoint=endpoint,
            status_code=str(response.status_code),
        ).inc()

        # Add trace headers to response
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Request-Id"] = request_id

        return response
    except Exception as e:
        # Log error
        duration_ms = int((time.time() - start_time) * 1000)
        log_json(
            "http.request.error",
            level="error",
            method=str(request.method),
            path=str(request.url.path),
            error=str(e)[:200],
            duration_ms=duration_ms,
        )

        # Update metrics for 500
        endpoint = str(request.url.path)
        http_requests_total.labels(
            method=str(request.method), endpoint=endpoint, status_code="500"
        ).inc()
        raise


# Add CORS middleware if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Test route to deliberately raise a 500 error (must be before signals_summary catch-all)
@app.get("/test500")
def test500():
    # Simulate an unhandled server error for metrics/logging validation
    raise RuntimeError("Simulated server error for testing")


# Register all routers
app.include_router(health.router)  # Health check routes (priority)
app.include_router(
    metrics.router
)  # Metrics routes (Day23+24) - before signals_summary catch-all
app.include_router(security.router)  # Security routes
app.include_router(ingest_x.router)  # X ingestion routes (Day8)
app.include_router(x_health.router)  # X health + simple read-only routes
app.include_router(dex.router)  # DEX routes (Day9)
app.include_router(rules.router)  # Rules evaluation routes (Day18)
app.include_router(signals_topic.router)  # Topic signals (Day9.1)
app.include_router(onchain.router)  # Onchain routes (Day10)
app.include_router(signals_heat.router)  # Heat signals (Day15&16-CardC)
app.include_router(signals_summary.router)  # Signals summary routes（day14？）
app.include_router(sentiment_routes.router)  # Sentiment routes (shim)
app.include_router(routes_expert_onchain.router)  # Expert routes（day14）
app.include_router(cards.router)  # Cards preview routes (Day19)
app.include_router(cards_send.router)  # Cards send routes (Day20)


@app.get("/")
def root():
    return {"message": "API root"}


@app.get("/healthz")
def healthz():
    return {"status": "healthy"}
