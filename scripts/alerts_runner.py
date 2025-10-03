#!/usr/bin/env python3
"""
Minimal alerting executor for Prometheus metrics.
Supports thresholds, debouncing, silence windows, and single-shot evaluation.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import yaml


class MetricsParser:
    """Parse Prometheus text format metrics."""

    @staticmethod
    def parse_metrics(text: str) -> Dict[str, Dict[str, float]]:
        """
        Parse Prometheus text format into nested dict.
        Returns: {metric_name: {label_str: value}}
        """
        metrics = defaultdict(lambda: defaultdict(float))

        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Match metric lines: metric_name{labels} value
            match = re.match(
                r"^([a-zA-Z_:][a-zA-Z0-9_:]*(?:_bucket|_count|_sum|_total)?)\{?(.*?)\}?\s+([0-9.\-+eE]+)$",
                line,
            )
            if match:
                try:
                    metric_name = match.group(1)
                    labels_str = match.group(2)
                    value = float(match.group(3))

                    # Store with label string as key
                    metrics[metric_name][labels_str] = value
                except Exception as e:
                    print(f"alert.parse_failed: line='{line}' error={e}")

        return dict(metrics)

    @staticmethod
    def extract_label_value(labels_str: str, label_name: str) -> Optional[str]:
        """Extract value of a specific label from label string."""
        pattern = f'{label_name}="([^"]*)"'
        match = re.search(pattern, labels_str)
        return match.group(1) if match else None


class AlertState:
    """Manage alert state including breaches and silence windows."""

    def __init__(self, state_file: str):
        self.state_file = state_file
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load state from file."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"alert.state_load_failed: {e}")

        return {
            "breaches": {},  # rule_name -> first_breach_time
            "silenced": {},  # rule_name -> silence_until_time
            "last_values": {},  # metric -> value (for delta calculation)
        }

    def save_state(self):
        """Save state to file."""
        try:
            with open(self.state_file, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"alert.state_save_failed: {e}")

    def is_silenced(self, rule_name: str) -> bool:
        """Check if rule is currently silenced."""
        if rule_name not in self.state["silenced"]:
            return False

        silence_until = datetime.fromisoformat(self.state["silenced"][rule_name])
        return datetime.now() < silence_until

    def set_silence(self, rule_name: str, seconds: int):
        """Set silence window for a rule."""
        silence_until = datetime.now() + timedelta(seconds=seconds)
        self.state["silenced"][rule_name] = silence_until.isoformat()

    def update_breach(
        self, rule_name: str, breached: bool, window_seconds: int
    ) -> bool:
        """
        Update breach state and check if alert should fire.
        Returns True if alert should fire (breached for full window).
        """
        now = datetime.now()

        if breached:
            if rule_name not in self.state["breaches"]:
                # First breach
                self.state["breaches"][rule_name] = now.isoformat()
                return False
            else:
                # Check if breached for full window
                first_breach = datetime.fromisoformat(self.state["breaches"][rule_name])
                if (now - first_breach).total_seconds() >= window_seconds:
                    return True
                return False
        else:
            # Clear breach if condition no longer met
            if rule_name in self.state["breaches"]:
                del self.state["breaches"][rule_name]
            return False

    def get_delta(self, metric_key: str, current_value: float) -> float:
        """Calculate delta from last value."""
        last_value = self.state["last_values"].get(metric_key, 0)
        delta = current_value - last_value
        self.state["last_values"][metric_key] = current_value
        return max(0, delta)  # Counters only increase


class AlertEvaluator:
    """Evaluate alert rules against metrics."""

    def __init__(self, state: AlertState):
        self.state = state

    def evaluate_rule(
        self, rule: Dict[str, Any], metrics: Dict[str, Dict[str, float]]
    ) -> tuple[bool, str]:
        """
        Evaluate a single rule against metrics.
        Returns: (breached, reason_string)
        """
        expr = rule["expr"]
        metric = rule.get("metric", "")
        threshold = rule["threshold"]

        if expr == "error_rate":
            # Calculate error rate for telegram_send_total
            ok_key = 'status="ok"'
            err_key = 'status="err"'

            ok_value = metrics.get("telegram_send_total", {}).get(ok_key, 0)
            err_value = metrics.get("telegram_send_total", {}).get(err_key, 0)

            # Use deltas for counters
            ok_delta = self.state.get_delta(f"telegram_send_total_{ok_key}", ok_value)
            err_delta = self.state.get_delta(
                f"telegram_send_total_{err_key}", err_value
            )

            total = ok_delta + err_delta
            if total == 0:
                return False, "no traffic"

            error_rate = err_delta / total
            breached = error_rate > threshold
            reason = f"error_rate={error_rate:.2%} > {threshold:.2%}"
            return breached, reason

        elif expr == "cards_degrade_delta":
            # Calculate delta for cards_degrade_count
            current = metrics.get("cards_degrade_count", {}).get("", 0)
            delta = self.state.get_delta("cards_degrade_count", current)

            breached = delta > threshold
            reason = f"delta={delta} > {threshold}"
            return breached, reason

        elif expr == "latency_p95":
            # Calculate P95 from histogram buckets
            histogram = metrics.get("pipeline_latency_ms_bucket", {})
            count_total = metrics.get("pipeline_latency_ms_count", {}).get("", 0)

            if count_total == 0:
                return False, "no samples"

            # Find P95 bucket
            p95_count = count_total * 0.95
            cumulative = 0
            p95_value = 0

            buckets = []
            for labels, count in histogram.items():
                if "le=" in labels:
                    le_match = re.search(r'le="([^"]+)"', labels)
                    if le_match:
                        le_value = le_match.group(1)
                        if le_value == "+Inf":
                            continue
                        buckets.append((float(le_value), count))

            buckets.sort()
            for bucket_value, count in buckets:
                cumulative = count
                if cumulative >= p95_count:
                    p95_value = bucket_value
                    break

            breached = p95_value > threshold
            reason = f"p95={p95_value}ms > {threshold}ms"
            return breached, reason

        elif expr == "error_delta":
            # Simple counter delta
            current = metrics.get(metric, {}).get("", 0)
            delta = self.state.get_delta(metric, current)

            breached = delta > threshold
            reason = f"delta={delta} > {threshold}"
            return breached, reason

        else:
            return False, f"unknown expr: {expr}"


class AlertNotifier:
    """Send alert notifications."""

    def __init__(
        self, webhook_url: Optional[str] = None, notify_script: Optional[str] = None
    ):
        self.webhook_url = webhook_url
        self.notify_script = notify_script

    def notify(
        self, rule_name: str, severity: str, reason: str, dry_run: bool = False
    ) -> bool:
        """
        Send notification for fired alert.
        Returns True if successful.
        """
        message = f"Alert: {rule_name} [{severity}] - {reason}"

        if dry_run:
            print(f"alert.notify_dryrun: {message}")
            return True

        # Try webhook first
        if self.webhook_url:
            return self._send_webhook(message)

        # Try script second
        if self.notify_script:
            return self._run_script(message, rule_name, severity)

        print(f"alert.notify_skipped: no notifier configured")
        return False

    def _send_webhook(self, message: str) -> bool:
        """Send notification via webhook."""
        try:
            data = json.dumps({"text": message}).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
            )

            # Retry with exponential backoff
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=5) as response:
                        if response.status == 200:
                            return True
                except urllib.error.URLError as e:
                    if attempt < 2:
                        time.sleep(2**attempt)
                        continue
                    raise

        except Exception as e:
            print(f"alert.notify_failed: webhook error: {e}")
            return False

    def _run_script(self, message: str, rule_name: str, severity: str) -> bool:
        """Run notification script."""
        try:
            env = os.environ.copy()
            env.update(
                {
                    "ALERT_MESSAGE": message,
                    "ALERT_RULE": rule_name,
                    "ALERT_SEVERITY": severity,
                }
            )

            result = subprocess.run(
                [self.notify_script],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                return True
            else:
                print(f"alert.notify_failed: script returned {result.returncode}")
                return False

        except Exception as e:
            print(f"alert.notify_failed: script error: {e}")
            return False


class AlertRunner:
    """Main alert runner."""

    def __init__(self, args):
        self.args = args
        self.state = AlertState(args.state_file)
        self.evaluator = AlertEvaluator(self.state)
        self.notifier = AlertNotifier(args.webhook_url, args.notify_script)
        self.rules = self._load_rules()

    def _load_rules(self) -> List[Dict[str, Any]]:
        """Load alert rules from YAML."""
        rules_file = "alerts.yml"
        if not os.path.exists(rules_file):
            print(f"alert.config_missing: {rules_file}")
            return []

        try:
            with open(rules_file, "r") as f:
                config = yaml.safe_load(f)
                return config.get("rules", [])
        except Exception as e:
            print(f"alert.config_failed: {e}")
            return []

    def fetch_metrics(self) -> Optional[Dict[str, Dict[str, float]]]:
        """Fetch and parse metrics from endpoint."""
        try:
            with urllib.request.urlopen(self.args.metrics, timeout=10) as response:
                text = response.read().decode("utf-8")
                return MetricsParser.parse_metrics(text)
        except Exception as e:
            print(f"alert.pull_failed: {e}")
            return None

    def evaluate_once(self):
        """Run one evaluation cycle."""
        # Fetch metrics
        metrics = self.fetch_metrics()
        if not metrics:
            return

        # Print retry observability
        retry_total = metrics.get("telegram_retry_total", {}).get("", 0)
        retry_delta = self.state.get_delta("telegram_retry_total", retry_total)
        if retry_delta > 0:
            print(f"alert.retry_observed: telegram_retry_delta={retry_delta}")

        # Evaluate each rule
        for rule in self.rules:
            rule_name = rule["name"]

            # Check if silenced
            if self.state.is_silenced(rule_name):
                print(f"alert.silenced: {rule_name}")
                continue

            # Evaluate rule
            breached, reason = self.evaluator.evaluate_rule(rule, metrics)

            # Update breach state with debouncing
            window = rule.get("window_seconds", self.args.min_breach_seconds)
            should_fire = self.state.update_breach(rule_name, breached, window)

            if should_fire:
                # Fire alert
                severity = rule.get("severity", "info")
                description = rule.get("description", reason)

                print(
                    f"alert.fired: name={rule_name} severity={severity} "
                    f'reason="{reason}" window={window}s'
                )

                # Send notification
                success = self.notifier.notify(
                    rule_name, severity, description, dry_run=self.args.dry_run
                )

                if success:
                    # Set silence window
                    silence = rule.get("silence_seconds", self.args.silence_seconds)
                    self.state.set_silence(rule_name, silence)
                    print(f"alert.silence_set: {rule_name} for {silence}s")

        # Save state
        self.state.save_state()

    def run(self):
        """Main run loop."""
        if self.args.once:
            # Single evaluation
            self.evaluate_once()
        else:
            # Continuous mode
            print(f"alert.runner_started: interval={self.args.interval}s")
            while True:
                try:
                    self.evaluate_once()
                    time.sleep(self.args.interval)
                except KeyboardInterrupt:
                    print("alert.runner_stopped: interrupted")
                    break
                except Exception as e:
                    print(f"alert.runner_error: {e}")
                    time.sleep(self.args.interval)


def main():
    parser = argparse.ArgumentParser(description="Minimal alerting executor")

    # Data sources
    parser.add_argument("--metrics", required=True, help="Metrics endpoint URL")
    parser.add_argument("--db", help="Database DSN (optional)")

    # Thresholds and windows
    parser.add_argument(
        "--min-breach-seconds",
        type=int,
        default=60,
        help="Global minimum debounce window",
    )
    parser.add_argument(
        "--silence-seconds", type=int, default=300, help="Global default silence window"
    )

    # Notification
    parser.add_argument("--webhook-url", help="Webhook URL for notifications")
    parser.add_argument("--notify-script", help="Script to run for notifications")

    # Execution mode
    parser.add_argument(
        "--once", action="store_true", help="Single evaluation then exit"
    )
    parser.add_argument(
        "--interval", type=int, default=30, help="Polling interval in seconds"
    )

    # State and options
    parser.add_argument(
        "--state-file", default=".alerts_state.json", help="State file path"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print only, no notifications"
    )

    args = parser.parse_args()

    # Validate notification config
    if not args.webhook_url and not args.notify_script:
        print("alert.config_error: must specify --webhook-url or --notify-script")
        sys.exit(1)

    # Run
    runner = AlertRunner(args)
    runner.run()


if __name__ == "__main__":
    main()
