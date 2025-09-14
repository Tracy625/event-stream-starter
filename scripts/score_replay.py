#!/usr/bin/env python3
"""
Replay scorer that evaluates replay results against golden dataset.
Generates report with metrics and per-case analysis.
"""

import os
import sys
import json
from typing import Dict, List, Any, Optional
from common_io import read_jsonl, read_json, save_json, safe_get


def calculate_percentile(values: List[float], percentile: float) -> float:
    """Calculate percentile value from a list."""
    if not values:
        return 0.0

    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile / 100)
    if index >= len(sorted_values):
        index = len(sorted_values) - 1
    return sorted_values[index]


def load_golden_data(filepath: str) -> Dict[str, Dict[str, Any]]:
    """Load golden dataset and index by event_key."""
    try:
        golden_list = read_jsonl(filepath)
        return {item['event_key']: item for item in golden_list}
    except FileNotFoundError:
        print(f"Error: Golden file not found: {filepath}", file=sys.stderr)
        sys.exit(2)
    except (KeyError, json.JSONDecodeError) as e:
        print(f"Error: Failed to parse golden file: {e}", file=sys.stderr)
        sys.exit(2)


def load_manifest(filepath: str) -> Dict[str, Any]:
    """Load replay manifest."""
    try:
        return read_json(filepath)
    except FileNotFoundError:
        print(f"Error: Manifest file not found: {filepath}", file=sys.stderr)
        print("Please run replay_e2e.sh first", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse manifest: {e}", file=sys.stderr)
        sys.exit(2)


def load_meta_file(event_key: str, idx: int, base_dir: str) -> Optional[Dict[str, Any]]:
    """Load metadata file for a specific case."""
    meta_path = os.path.join(base_dir, f"{idx}_{event_key}.meta.json")
    if os.path.exists(meta_path):
        try:
            return read_json(meta_path)
        except:
            pass
    return None


def load_response_file(event_key: str, idx: int, base_dir: str) -> Optional[Dict[str, Any]]:
    """Load response file for a specific case."""
    response_path = os.path.join(base_dir, f"{idx}_{event_key}.response.json")
    if os.path.exists(response_path):
        try:
            return read_json(response_path)
        except:
            pass
    return None


def evaluate_case(golden: Dict[str, Any],
                  replay_case: Dict[str, Any],
                  base_dir: str) -> Dict[str, Any]:
    """Evaluate a single test case."""
    event_key = golden['event_key']
    idx = replay_case.get('idx', 0)

    # Load additional data
    meta = load_meta_file(event_key, idx, base_dir)
    response = load_response_file(event_key, idx, base_dir)

    status_code = replay_case.get('status_code', 0)

    # Determine actual alert status (only for 200 responses)
    actual_alert = False
    alert_reason = None

    if status_code == 200:
        # Try to determine alert from response
        if response:
            # Check alert fields in order of priority
            for field in ['alert', 'should_alert', 'alerted']:
                if field in response and response[field] is True:
                    actual_alert = True
                    alert_reason = f"response.{field}=true"
                    break

            if not actual_alert:
                # No alert signal found
                alert_reason = "no_alert_signal"
        else:
            # No response file but status is 200
            alert_reason = "no_response_file"
    else:
        # Non-200 response
        alert_reason = f"status_code={status_code}"

    # Expected alert from golden data
    expected_alert = safe_get(golden, 'expected.should_alert', False)

    # Check if hit (correct prediction) - only for 200 responses
    hit = (actual_alert == expected_alert) if status_code == 200 else None

    # Check for degradation
    degrade = (status_code != 200)
    degrade_reason = None

    if degrade:
        degrade_reason = f"status_code={status_code}"
    elif meta and meta.get('degrade', False):
        degrade = True
        degrade_reason = "meta.degrade=true"

    return {
        'event_key': event_key,
        'expected_alert': expected_alert,
        'actual_alert': actual_alert,
        'hit': hit,
        'status': replay_case.get('status', 'unknown'),
        'status_code': status_code,
        'latency_ms': replay_case.get('latency_ms', 0),
        'degrade': degrade,
        'degrade_reason': degrade_reason,
        'reason': alert_reason
    }


def generate_report(golden_path: str,
                   manifest_path: str,
                   replay_dir: str) -> Dict[str, Any]:
    """Generate comprehensive scoring report."""

    # Load data
    golden_data = load_golden_data(golden_path)
    manifest = load_manifest(manifest_path)

    # Track missing cases
    golden_keys = set(golden_data.keys())
    manifest_keys = set()

    # Process each case
    cases = manifest.get('cases', [])
    evaluated_cases = []
    latencies = []
    error_distribution = {}
    successful_cases = []  # Only 200 responses

    for replay_case in cases:
        event_key = replay_case.get('event_key')
        if event_key:
            manifest_keys.add(event_key)

        if not event_key or event_key not in golden_data:
            continue

        eval_result = evaluate_case(
            golden_data[event_key],
            replay_case,
            replay_dir
        )
        evaluated_cases.append(eval_result)

        # Collect latency
        if eval_result['latency_ms'] > 0:
            latencies.append(eval_result['latency_ms'])

        # Track error distribution
        status_code = eval_result['status_code']
        if status_code != 200:
            if status_code == 0:
                error_key = "timeout"
            else:
                error_key = str(status_code)
            error_distribution[error_key] = error_distribution.get(error_key, 0) + 1
        else:
            # Track successful cases for accuracy calculation
            successful_cases.append(eval_result)

    # Calculate alignment
    missing_in_manifest = list(golden_keys - manifest_keys)
    missing_in_golden = list(manifest_keys - golden_keys)

    # Calculate metrics
    total_golden = len(golden_data)
    success_count = len(successful_cases)
    pipeline_success_rate = success_count / total_golden if total_golden > 0 else 0.0

    # Calculate alert accuracy only on successful cases
    alert_accuracy_on_success = 0.0
    if successful_cases:
        hits_on_success = sum(1 for case in successful_cases if case['hit'] is True)
        alert_accuracy_on_success = hits_on_success / len(successful_cases)

    cards_degrade_count = sum(1 for case in evaluated_cases if case['degrade'])

    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    p95_latency = calculate_percentile(latencies, 95) if latencies else 0.0

    # Backward compatibility: hit_rate = alert_accuracy_on_success
    hit_rate = alert_accuracy_on_success

    # Determine pass/fail based on new criteria
    passed = (pipeline_success_rate >= 0.9 and
              alert_accuracy_on_success >= 0.8 and
              cards_degrade_count <= 2)

    # Build report
    report = {
        'summary': {
            'total_cases': len(evaluated_cases),
            'pipeline_success_rate': round(pipeline_success_rate, 4),
            'alert_accuracy_on_success': round(alert_accuracy_on_success, 4),
            'missing_in_manifest': missing_in_manifest,
            'missing_in_golden': missing_in_golden,
            'skipped_count': len(missing_in_manifest) + len(missing_in_golden),
            'hits': len([c for c in successful_cases if c['hit'] is True]),
            'hit_rate': round(hit_rate, 4),  # Backward compatibility
            'avg_latency_ms': round(avg_latency, 2),
            'p95_latency_ms': round(p95_latency, 2),
            'cards_degrade_count': cards_degrade_count,
            'error_distribution': error_distribution,
            'passed': passed
        },
        'by_case': evaluated_cases
    }

    return report


def main():
    """Main entry point."""
    # Paths
    golden_path = "demo/golden/golden.jsonl"
    manifest_path = "logs/day22/replay_raw/manifest.json"
    replay_dir = "logs/day22/replay_raw"
    output_path = "logs/day22/replay_report.json"

    print("=== Replay Scorer ===")
    print()

    # Check soft fail mode
    soft_fail = os.environ.get('SCORE_SOFT_FAIL', 'false').lower() in ['true', '1', 'yes']

    # Generate report
    print(f"Loading golden dataset: {golden_path}")
    print(f"Loading replay manifest: {manifest_path}")

    report = generate_report(golden_path, manifest_path, replay_dir)

    # Save report
    save_json(report, output_path)
    print(f"\nReport saved to: {output_path}")

    # Print summary
    summary = report['summary']
    print("\n=== Summary ===")
    print(f"Total cases: {summary['total_cases']}")
    print(f"Pipeline success rate: {summary['pipeline_success_rate']:.2%}")
    print(f"Alert accuracy (on success): {summary['alert_accuracy_on_success']:.2%}")
    print(f"Average latency: {summary['avg_latency_ms']:.2f}ms")
    print(f"P95 latency: {summary['p95_latency_ms']:.2f}ms")
    print(f"Degraded cases: {summary['cards_degrade_count']}")

    if summary['missing_in_manifest']:
        print(f"\nMissing in manifest: {', '.join(summary['missing_in_manifest'])}")
    if summary['missing_in_golden']:
        print(f"Missing in golden: {', '.join(summary['missing_in_golden'])}")

    if summary['error_distribution']:
        print("\nError distribution:")
        for code, count in sorted(summary['error_distribution'].items()):
            print(f"  {code}: {count}")

    # Determine exit code
    if summary['passed']:
        print("\n✅ PASSED: Pipeline success ≥ 90%, Alert accuracy ≥ 80%, Degrade count ≤ 2")
        sys.exit(0)
    else:
        print("\n❌ FAILED: Pipeline success < 90% or Alert accuracy < 80% or Degrade count > 2")
        if soft_fail:
            print("⚠️  SCORE_SOFT_FAIL=true: Returning 0 despite failure")
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()