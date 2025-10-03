"""
Prometheus metrics exporter for building text format output.
Provides clean separation from metrics collection/storage.
"""

from collections import defaultdict
from typing import Any, Dict, List, Optional

# Global metric registry
_metrics_registry: Dict[str, Any] = {}


def register_counter(
    name: str, help_text: str, labels: Optional[Dict[str, str]] = None, value: float = 0
):
    """Register or update a counter metric."""
    if name not in _metrics_registry:
        _metrics_registry[name] = {
            "type": "counter",
            "help": help_text,
            "values": defaultdict(float),
        }

    label_str = _format_labels(labels)
    _metrics_registry[name]["values"][label_str] = value


def register_gauge(
    name: str, help_text: str, labels: Optional[Dict[str, str]] = None, value: float = 0
):
    """Register or update a gauge metric."""
    if name not in _metrics_registry:
        _metrics_registry[name] = {"type": "gauge", "help": help_text, "values": {}}

    label_str = _format_labels(labels)
    _metrics_registry[name]["values"][label_str] = value


def register_histogram(
    name: str,
    help_text: str,
    buckets: List[float],
    samples: Optional[List[float]] = None,
):
    """Register or update a histogram metric with samples."""
    if name not in _metrics_registry:
        _metrics_registry[name] = {
            "type": "histogram",
            "help": help_text,
            "buckets": buckets,
            "samples": [],
        }

    if samples:
        _metrics_registry[name]["samples"] = samples


def _format_labels(labels: Optional[Dict[str, str]]) -> str:
    """Format labels for Prometheus text format."""
    if not labels:
        return ""
    parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


def build_prom_text() -> str:
    """
    Build Prometheus text format output with complete metrics.

    Returns complete Prometheus text with:
    - pipeline_latency_ms histogram with fixed buckets
    - All registered counters and gauges
    - Proper HELP and TYPE annotations
    - Guaranteed presence of key metrics: hf_degrade_count, outbox_backlog, pipeline_latency_ms
    """
    lines = []

    # Ensure key metrics are registered with defaults if not present
    if "hf_degrade_count" not in _metrics_registry:
        register_counter("hf_degrade_count", "HuggingFace degrade count", value=0)

    if "outbox_backlog" not in _metrics_registry:
        register_gauge("outbox_backlog", "Push outbox backlog size", value=0)

    # Always output pipeline_latency_ms histogram (even if empty)
    lines.append(
        "# HELP pipeline_latency_ms Latency histogram of pipeline in milliseconds"
    )
    lines.append("# TYPE pipeline_latency_ms histogram")

    # Fixed buckets for pipeline_latency_ms
    buckets = [50, 100, 200, 500, 1000, 2000, 5000]

    # Get samples if registered
    samples = []
    if "pipeline_latency_ms" in _metrics_registry:
        samples = _metrics_registry["pipeline_latency_ms"].get("samples", [])

    # Calculate bucket counts
    for bucket in buckets:
        count = sum(1 for s in samples if s <= bucket)
        lines.append(f'pipeline_latency_ms_bucket{{le="{bucket}"}} {count}')

    # +Inf bucket
    lines.append(f'pipeline_latency_ms_bucket{{le="+Inf"}} {len(samples)}')

    # Sum and count
    total_sum = sum(samples) if samples else 0
    lines.append(f"pipeline_latency_ms_sum {total_sum}")
    lines.append(f"pipeline_latency_ms_count {len(samples)}")

    # Output other registered metrics
    for name, metric in _metrics_registry.items():
        if name == "pipeline_latency_ms":
            continue  # Already handled above

        lines.append("")
        lines.append(f"# HELP {name} {metric['help']}")
        lines.append(f"# TYPE {name} {metric['type']}")

        if metric["type"] in ["counter", "gauge"]:
            if metric["values"]:
                for label_str, value in metric["values"].items():
                    lines.append(f"{name}{label_str} {value}")
            else:
                # Output 0 as placeholder
                lines.append(f"{name} 0")

    # Add standard metrics if not already present
    standard_metrics = [
        (
            "telegram_send_total",
            "counter",
            "Count of Telegram send attempts by status/code",
        ),
        ("telegram_retry_total", "counter", "Total number of Telegram send retries"),
        ("cards_degrade_count", "counter", "Total number of degraded events"),
        ("config_reload_total", "counter", "Total number of config reloads"),
        (
            "config_reload_errors_total",
            "counter",
            "Total number of config reload errors",
        ),
        ("config_version", "gauge", "Current config version"),
        (
            "config_last_success_unixtime",
            "gauge",
            "Unix timestamp of last successful config reload",
        ),
        ("up", "gauge", "1 if metrics handler is healthy"),
        ("build_info", "gauge", "Build information"),
    ]

    for name, metric_type, help_text in standard_metrics:
        if name not in _metrics_registry:
            lines.append("")
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {metric_type}")
            lines.append(f"{name} 0")

    return "\n".join(lines) + "\n"


def clear_registry():
    """Clear all registered metrics (useful for testing)."""
    global _metrics_registry
    _metrics_registry = {}


def update_from_hotreload_registry(registry_metrics: Dict[str, Any]):
    """Update metrics from hot reload registry."""
    if not registry_metrics:
        return

    # Update config reload metrics
    if "config_reload_total" in registry_metrics:
        register_counter(
            "config_reload_total",
            "Total number of config reloads",
            value=registry_metrics["config_reload_total"],
        )

    if "config_reload_errors_total" in registry_metrics:
        register_counter(
            "config_reload_errors_total",
            "Total number of config reload errors",
            value=registry_metrics["config_reload_errors_total"],
        )

    if "config_version" in registry_metrics:
        register_gauge(
            "config_version",
            "Current config version",
            labels={"sha": registry_metrics["config_version"]},
            value=1,
        )

    if "config_last_success_unixtime" in registry_metrics:
        register_gauge(
            "config_last_success_unixtime",
            "Unix timestamp of last successful config reload",
            value=registry_metrics["config_last_success_unixtime"],
        )


def export_text() -> str:
    """
    Backward compatibility alias for build_prom_text().

    Some modules may still use export_text(), so we provide this alias.
    """
    return build_prom_text()
