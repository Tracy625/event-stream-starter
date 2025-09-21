"""
Metrics endpoint for Prometheus scraping.

Exposes observability metrics in Prometheus v0.0.4 text format.
Controlled by METRICS_EXPOSED environment variable.
"""

import os
import time
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response
from prometheus_client import generate_latest
from sqlalchemy import text

# Import from renamed module to avoid confusion
from api.core.metrics_store import log_json
from api.core.metrics_exporter import (
    build_prom_text,
    register_counter,
    register_gauge,
    register_histogram,
    update_from_hotreload_registry,
    clear_registry
)
from api.config.hotreload import get_registry
from api.core import metrics as metrics_core
from api.core.metrics import PROM_REGISTRY
from api.cache import get_redis_client
from api.core.api_metrics import _REDIS_ZSET_KEY, _WINDOW_SECONDS
from api.database import with_db
from api.tasks.beat import get_last_heartbeat

router = APIRouter()


def _record_outbox_backlog_metric() -> None:
    """Collect outbox backlog count directly from the database."""
    try:
        with with_db() as session:
            result = session.execute(
                text(
                    "SELECT COUNT(*) FROM push_outbox WHERE status IN ('pending','retry')"
                )
            )
            backlog = int(result.scalar() or 0)
            register_gauge(
                "outbox_backlog",
                "Push outbox backlog size",
                value=backlog,
            )
    except Exception as exc:  # pragma: no cover - metrics endpoint should degrade quietly
        log_json(stage="metrics.outbox_backlog_error", error=str(exc))


def _record_beat_metrics() -> None:
    """Expose beat heartbeat timestamp and age based on Redis key."""
    last = get_last_heartbeat()
    if last is None:
        log_json(stage="metrics.beat_heartbeat_missing", message="No heartbeat recorded")
        register_gauge(
            "beat_heartbeat_timestamp",
            "Last beat heartbeat timestamp",
            value=0,
        )
        register_gauge(
            "beat_heartbeat_age_seconds",
            "Seconds since the last beat heartbeat",
            value=0,
        )
        return

    now = time.time()
    age = max(0.0, now - last)
    register_gauge(
        "beat_heartbeat_timestamp",
        "Last beat heartbeat timestamp",
        value=last,
    )
    register_gauge(
        "beat_heartbeat_age_seconds",
        "Seconds since the last beat heartbeat",
        value=age,
    )


def _record_total_apis_gauge() -> None:
    redis = get_redis_client()
    if redis is None:
        register_gauge("total_apis", "Total successful outbound API calls in the last 24h", value=0)
        return

    now = time.time()
    window_start = now - _WINDOW_SECONDS
    try:
        redis.zremrangebyscore(_REDIS_ZSET_KEY, 0, window_start)
        total = redis.zcount(_REDIS_ZSET_KEY, window_start, now)
    except Exception as exc:  # pragma: no cover
        log_json(stage="metrics.total_apis_error", error=str(exc))
        total = 0

    register_gauge(
        "total_apis",
        "Total successful outbound API calls in the last 24 hours",
        value=float(total),
    )


@router.get("/metrics")
@router.head("/metrics")
async def metrics_endpoint():
    """
    Expose metrics in Prometheus text format.

    Returns 404 if METRICS_EXPOSED is not true.
    Returns 500 with up=0 if handler encounters an error.
    """
    # Check if metrics are exposed (read dynamically on each request)
    metrics_exposed = os.getenv("METRICS_EXPOSED", "false").lower() == "true"

    if not metrics_exposed:
        log_json(
            stage="metrics.denied",
            reason="METRICS_EXPOSED=false",
            message="Metrics endpoint access denied"
        )
        return Response(content="Not Found", status_code=404)

    try:
        # Clear registry to ensure fresh metrics
        clear_registry()

        # Set health metric to 1 (healthy)
        register_gauge("up", "1 if metrics handler is healthy", value=1)

        # Update config hot reload metrics from registry
        try:
            registry = get_registry()
            registry_metrics = registry.get_metrics()
            update_from_hotreload_registry(registry_metrics)

        except Exception as e:
            # Log but don't fail if registry is not available
            log_json(
                stage="metrics.registry_error",
                error=str(e)[:200],
                message="Failed to get config registry metrics"
            )
            # Still set a default config_version to ensure metric exists
            register_gauge("config_version", "Current config version",
                          labels={"sha": "unknown"}, value=1)

        # Set build info if available
        build_version = os.getenv("BUILD_VERSION", "")
        build_commit = os.getenv("BUILD_COMMIT", "")
        if build_version or build_commit:
            register_gauge("build_info", "Build information",
                          labels={"version": build_version or "",
                                 "commit": build_commit or ""},
                          value=1)

        # Initialize standard metrics with zero values
        register_counter("telegram_send_total",
                        "Count of Telegram send attempts by status/code",
                        value=0)
        register_counter("telegram_retry_total",
                        "Total number of Telegram send retries",
                        value=0)
        register_counter("cards_degrade_count",
                        "Total number of degraded events",
                        value=0)

        # Register histogram for pipeline latency (even if empty)
        register_histogram("pipeline_latency_ms",
                          "Latency histogram of pipeline in milliseconds",
                          buckets=[50, 100, 200, 500, 1000, 2000, 5000],
                          samples=[])

        _record_outbox_backlog_metric()
        _record_beat_metrics()
        _record_total_apis_gauge()

        # Build Prometheus text
        metrics_export_text = build_prom_text().strip()
        metrics_core_text = metrics_core.export_text().strip()

        sections = [metrics_export_text]
        if metrics_core_text:
            sections.append(metrics_core_text)

        prom_text = generate_latest(PROM_REGISTRY).decode("utf-8").strip()
        if prom_text:
            sections.append(prom_text)

        metrics_text = "\n\n".join(sections) + "\n"

        # Return with proper content type for Prometheus v0.0.4
        return PlainTextResponse(
            content=metrics_text,
            media_type="text/plain; version=0.0.4; charset=utf-8",
            status_code=200
        )

    except Exception as e:
        # On error, set up=0 and return 500
        log_json(
            stage="metrics.error",
            error=str(e)[:500],
            message="Error generating metrics"
        )

        try:
            # Try to set up gauge to 0
            clear_registry()
            register_gauge("up", "1 if metrics handler is healthy", value=0)

            # Try to export whatever we have
            metrics_text = build_prom_text()
        except:
            # Last resort: return minimal metrics with up=0
            metrics_text = "# HELP up 1 if metrics handler is healthy\n# TYPE up gauge\nup 0\n"

        return PlainTextResponse(
            content=metrics_text,
            media_type="text/plain; version=0.0.4; charset=utf-8",
            status_code=500
        )
