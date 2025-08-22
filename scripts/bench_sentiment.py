#!/usr/bin/env python3
"""
Sentiment analysis benchmark script.

Measures performance of analyze_sentiment() on golden dataset.
Outputs avg_ms and p95_ms metrics.

Usage:
    python scripts/bench_sentiment.py
    
    # Or with environment variables
    N=100 SENTIMENT_BACKEND=hf python scripts/bench_sentiment.py
"""

import os
import sys
import json
import time
from typing import List, Tuple

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.filter import analyze_sentiment


def load_golden_data() -> List[dict]:
    """Load golden dataset from golden.jsonl."""
    golden_path = os.path.join(os.path.dirname(__file__), "golden.jsonl")
    
    if not os.path.exists(golden_path):
        print(f"Error: {golden_path} not found")
        sys.exit(1)
    
    samples = []
    with open(golden_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    sample = json.loads(line)
                    samples.append(sample)
                except json.JSONDecodeError as e:
                    print(f"Error parsing JSON: {e}")
                    continue
    
    if not samples:
        print("Error: No valid samples found in golden.jsonl")
        sys.exit(1)
    
    return samples


def benchmark_sentiment(samples: List[dict], n_runs: int) -> Tuple[float, float, float]:
    """
    Run sentiment analysis N times and calculate timing metrics.
    
    Args:
        samples: List of golden samples
        n_runs: Number of benchmark runs
    
    Returns:
        (avg_ms, p50_ms, p95_ms) tuple
    """
    timings = []
    
    # Check backend
    backend = os.getenv("SENTIMENT_BACKEND", "rules")
    
    # If HF requested but not available, fallback to rules
    if backend == "hf":
        try:
            # Try to import transformers to check if HF is available
            import transformers
        except ImportError:
            print("rules-only")
            sys.exit(0)
    
    # Run benchmark
    for run in range(n_runs):
        run_start = time.perf_counter()
        
        for sample in samples:
            text = sample["text"]
            # Call the actual analyze_sentiment function
            label, score = analyze_sentiment(text)
        
        run_end = time.perf_counter()
        run_ms = (run_end - run_start) * 1000  # Convert to milliseconds
        timings.append(run_ms)
    
    # Calculate metrics
    timings.sort()
    avg_ms = sum(timings) / len(timings)
    
    # Calculate p50
    p50_index = int(len(timings) * 0.5)
    if p50_index >= len(timings):
        p50_index = len(timings) - 1
    p50_ms = timings[p50_index]
    
    # Calculate p95
    p95_index = int(len(timings) * 0.95)
    if p95_index >= len(timings):
        p95_index = len(timings) - 1
    p95_ms = timings[p95_index]
    
    return avg_ms, p50_ms, p95_ms


def main():
    """Main benchmark execution."""
    # Get number of runs from environment
    n_runs = int(os.getenv("N", "20"))
    backend = os.getenv("SENTIMENT_BACKEND", "rules")
    
    # Load golden data
    samples = load_golden_data()
    
    # Run benchmark
    avg_ms, p50_ms, p95_ms = benchmark_sentiment(samples, n_runs)
    
    # Output results with backend info
    print(f"Backend: {backend}")
    print(f"avg_ms: {avg_ms:.2f}")
    print(f"p50_ms: {p50_ms:.2f}")
    print(f"p95_ms: {p95_ms:.2f}")


if __name__ == "__main__":
    main()