#!/usr/bin/env python
"""
Smoke test for sentiment analysis backends.

Tests both rules and HF backends on a fixed set of inputs.
Supports batch processing from JSONL files.
"""

import os
import sys
import json
import time
import signal
import argparse
from typing import List, Dict, Any

import requests

# Handle broken pipe gracefully
signal.signal(signal.SIGPIPE, signal.SIG_DFL) if hasattr(signal, 'SIGPIPE') else None


TEST_INPUTS = [
    "I love this",
    "this is terrible",
    "great job",
    "awful mess"
]

API_URL = "http://localhost:8000/sentiment/analyze"


def call_api(text: str, timeout: float = 3.0) -> Dict[str, Any]:
    """Call sentiment API and pretty-print the response."""
    response = requests.post(API_URL, json={"text": text}, timeout=timeout)
    payload = response.json()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def _assert_degrade(payload: Dict[str, Any], expected_reason: str | tuple[str, ...]):
    if not payload.get("degrade"):
        print("Expected degrade flag in response", file=sys.stderr)
        sys.exit(1)
    reasons = (expected_reason,) if isinstance(expected_reason, str) else expected_reason
    if payload.get("reason") not in reasons:
        print(f"Unexpected degrade reason: {payload.get('reason')} (want {reasons})", file=sys.stderr)
        sys.exit(1)


def run_online_smoke() -> None:
    """Trigger HuggingFace online failures and verify fallback + metrics."""
    print("=== HF online smoke ===")

    # Scenario A: auth failure -> degrade via HTTP route (path=get/post handled server-side)
    os.environ["SENTIMENT_BACKEND"] = "api"
    os.environ["HF_API_TOKEN"] = "invalid-token"
    os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)
    auth_payload = call_api("hello")
    _assert_degrade(auth_payload, ("auth", "http_4xx", "http_401", "http_403"))

    # Scenario B: force timeout from script path (direct fallback invocation)
    os.environ["HF_API_TOKEN"] = "placeholder-token"
    os.environ["HF_API_BASE"] = "https://10.255.255.1"
    os.environ["SENTIMENT_TIMEOUT_S"] = "0.001"

    from api.hf_sentiment import analyze_with_fallback

    script_payload, _ = analyze_with_fallback("world", path_label="script")
    print(json.dumps(script_payload, ensure_ascii=False, indent=2))
    _assert_degrade(script_payload, "timeout")

    print("smoke ok")


def test_backend(backend: str):
    """Test a specific backend."""
    print(f"\n=== Testing backend: {backend} ===")
    
    # Set backend
    os.environ["SENTIMENT_BACKEND"] = backend
    
    try:
        # Import after setting env to ensure fresh module state
        from api.filter import analyze_sentiment
        
        for text in TEST_INPUTS:
            try:
                label, score = analyze_sentiment(text)
                print(f"  [{backend}] '{text}' -> label={label}, score={score:.3f}")
            except Exception as e:
                print(f"  [{backend}] '{text}' -> ERROR: {e}")
                if os.getenv("SENTIMENT_STRICT", "0") == "1":
                    sys.exit(1)
                    
    except Exception as e:
        print(f"  Failed to test {backend}: {e}")
        if os.getenv("SENTIMENT_STRICT", "0") == "1":
            sys.exit(1)


def load_jsonl(filepath: str) -> List[Dict[str, Any]]:
    """Load JSONL file and extract texts."""
    texts = []
    with open(filepath, 'r') as f:
        for line in f:
            if line.strip():
                data = json.loads(line)
                if 'text' in data:
                    texts.append(data['text'])
    return texts


def process_batch_hf(texts: List[str]) -> List[Dict[str, Any]]:
    """Process batch using HfClient."""
    from api.services.hf_client import HfClient
    
    client = HfClient()
    return client.predict_sentiment_batch(texts)


def process_batch_rules(texts: List[str]) -> List[Dict[str, Any]]:
    """Process batch using rules backend."""
    from api.filter import analyze_sentiment
    
    # Ensure rules backend is used
    original_backend = os.environ.get("SENTIMENT_BACKEND", "rules")
    os.environ["SENTIMENT_BACKEND"] = "rules"
    
    results = []
    for text in texts:
        try:
            label, score = analyze_sentiment(text)
            results.append({
                "label": label,
                "score": score,
                "probs": None  # Rules backend doesn't provide probabilities
            })
        except Exception as e:
            results.append({
                "label": "neu",
                "score": 0.0,
                "error": str(e)
            })
    
    # Restore original backend
    os.environ["SENTIMENT_BACKEND"] = original_backend
    return results


def run_batch(batch_file: str, backend: str, summary_json: bool = False):
    """Run batch processing with specified backend."""
    if not summary_json:
        print(f"\n=== Batch Processing: backend={backend} ===")
    
    # Load texts
    texts = load_jsonl(batch_file)
    if not texts:
        if not summary_json:
            print(f"No valid texts found in {batch_file}")
        return
    
    if not summary_json:
        print(f"Loaded {len(texts)} texts from {batch_file}")
    
    # Process batch
    t0 = time.time()
    
    if backend == "hf":
        results = process_batch_hf(texts)
    elif backend == "rules":
        results = process_batch_rules(texts)
    else:
        if not summary_json:
            print(f"Unknown backend: {backend}")
        return
    
    elapsed_ms = int((time.time() - t0) * 1000)
    
    # Calculate summary stats
    success_count = sum(1 for r in results if 'error' not in r)
    fail_count = len(results) - success_count
    has_degrade = any('degrade' in r for r in results)
    
    if summary_json:
        # Output only JSON summary
        summary = {
            "input_count": len(texts),
            "success_count": success_count,
            "fail_count": fail_count,
            "elapsed_ms": elapsed_ms,
            "degraded": has_degrade
        }
        try:
            print(json.dumps(summary))
            sys.stdout.flush()
        except BrokenPipeError:
            sys.exit(0)
    else:
        # Output results line by line
        for result in results:
            try:
                print(json.dumps(result))
            except BrokenPipeError:
                sys.exit(0)
        
        # Print text summary
        try:
            print(f"\n=== Summary ===")
            print(f"Input count: {len(texts)}")
            print(f"Success count: {success_count}")
            print(f"Fail count: {fail_count}")
            print(f"Elapsed time: {elapsed_ms}ms")
            print(f"Has degradation: {has_degrade}")
            sys.stdout.flush()
        except BrokenPipeError:
            sys.exit(0)


def main():
    """Run smoke tests for sentiment analysis."""
    parser = argparse.ArgumentParser(description='Sentiment analysis smoke test')
    parser.add_argument('--batch', type=str, help='JSONL file for batch processing')
    parser.add_argument('--backend', type=str, choices=['hf', 'rules'], 
                       default='hf', help='Backend to use (hf or rules)')
    parser.add_argument('--summary-json', action='store_true',
                       help='Output only JSON summary (for batch mode)')
    parser.add_argument('--legacy', action='store_true',
                        help='Run legacy local smoke instead of online fallback checks')
    
    args = parser.parse_args()
    
    if args.batch:
        run_batch(args.batch, args.backend, args.summary_json)
        return

    if args.legacy:
        if not args.summary_json:
            print("Sentiment Analysis Smoke Test")
            print("=" * 40)
            test_backend("rules")
            test_backend("hf")
            print("\n" + "=" * 40)
            print("Smoke test completed")
        return

    run_online_smoke()


if __name__ == "__main__":
    main()
