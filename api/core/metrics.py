"""Lightweight metrics registry for monitoring"""
import threading
from typing import Dict, List, Optional, Any
from collections import defaultdict


class Counter:
    """Counter metric that can only increase"""
    
    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help = help_text
        self.values = defaultdict(float)
        self.lock = threading.Lock()
    
    def inc(self, labels: Optional[Dict[str, str]] = None, value: int = 1):
        """Increment counter by value"""
        label_str = self._format_labels(labels)
        with self.lock:
            self.values[label_str] += value
    
    def _format_labels(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"
    
    def export(self) -> str:
        """Export metric in Prometheus text format"""
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        with self.lock:
            for label_str, value in self.values.items():
                lines.append(f"{self.name}{label_str} {value}")
        return "\n".join(lines)


class Gauge:
    """Gauge metric that can go up and down"""
    
    def __init__(self, name: str, help_text: str):
        self.name = name
        self.help = help_text
        self.values = {}
        self.lock = threading.Lock()
    
    def set(self, value: float, labels: Optional[Dict[str, str]] = None):
        """Set gauge to value"""
        label_str = self._format_labels(labels)
        with self.lock:
            self.values[label_str] = value
    
    def _format_labels(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"
    
    def export(self) -> str:
        """Export metric in Prometheus text format"""
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        with self.lock:
            for label_str, value in self.values.items():
                lines.append(f"{self.name}{label_str} {value}")
        return "\n".join(lines)


class Histogram:
    """Histogram metric with configurable buckets (cumulative, computed on export)"""
    
    def __init__(self, name: str, help_text: str, buckets: List[int]):
        self.name = name
        self.help = help_text
        self.buckets = sorted(buckets)
        # Keep raw samples, calculate cumulative buckets on export to avoid double-counting
        self.samples = defaultdict(list)   # label_str -> List[float]
        self.sums = defaultdict(float)     # label_str -> float
        self.counts = defaultdict(int)     # label_str -> int
        self.lock = threading.Lock()
    
    def observe(self, value_ms: float, labels: Optional[Dict[str, str]] = None):
        """Record an observation"""
        label_str = self._format_labels(labels)
        with self.lock:
            self.samples[label_str].append(value_ms)
            self.sums[label_str] += value_ms
            self.counts[label_str] += 1
    
    def _format_labels(self, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"
    
    def export(self) -> str:
        """Export metric in Prometheus text format"""
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        with self.lock:
            for label_str, count in self.counts.items():
                # Calculate cumulative buckets: count samples <= threshold for each threshold
                values = self.samples.get(label_str, [])
                for bucket in self.buckets:
                    c = sum(1 for v in values if v <= bucket)
                    bucket_label = (
                        label_str.rstrip("}") + f',le="{bucket}"' + "}"
                        if label_str else f'{{le="{bucket}"}}'
                    )
                    lines.append(f"{self.name}_bucket{bucket_label} {c}")
                # +Inf bucket
                inf_label = label_str.rstrip("}") + ',le="+Inf"' + "}" if label_str else '{le="+Inf"}'
                lines.append(f"{self.name}_bucket{inf_label} {count}")
                # Sum and count
                lines.append(f"{self.name}_sum{label_str} {self.sums[label_str]}")
                lines.append(f"{self.name}_count{label_str} {count}")
        return "\n".join(lines)


# Global registry
_registry = {}
_registry_lock = threading.Lock()


def counter(name: str, help_text: str) -> Counter:
    """Register and return a counter metric"""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = Counter(name, help_text)
        return _registry[name]


def gauge(name: str, help_text: str) -> Gauge:
    """Register and return a gauge metric"""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = Gauge(name, help_text)
        return _registry[name]


def histogram(name: str, help_text: str, buckets: List[int]) -> Histogram:
    """Register and return a histogram metric"""
    with _registry_lock:
        if name not in _registry:
            _registry[name] = Histogram(name, help_text, buckets)
        return _registry[name]


def export_text() -> str:
    """Export all metrics in Prometheus text format"""
    lines = []
    with _registry_lock:
        for metric in _registry.values():
            lines.append(metric.export())
    return "\n\n".join(lines)