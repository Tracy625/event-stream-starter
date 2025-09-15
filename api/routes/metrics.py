"""
Metrics endpoint for Prometheus scraping.

Exposes observability metrics in Prometheus v0.0.4 text format.
Controlled by METRICS_EXPOSED environment variable.
"""

import os
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

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

router = APIRouter()


@router.get("/metrics")
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

        # Build Prometheus text
        metrics_text = build_prom_text()

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