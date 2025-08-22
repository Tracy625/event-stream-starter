#!/usr/bin/env python
"""
Smoke test for sentiment analysis backends.

Tests both rules and HF backends on a fixed set of inputs.
Prints results for manual verification.
"""

import os
import sys


TEST_INPUTS = [
    "I love this",
    "this is terrible",
    "great job",
    "awful mess"
]


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


def main():
    """Run smoke tests for all backends."""
    print("Sentiment Analysis Smoke Test")
    print("=" * 40)
    
    # Test rules backend
    test_backend("rules")
    
    # Test HF backend
    test_backend("hf")
    
    print("\n" + "=" * 40)
    print("Smoke test completed")


if __name__ == "__main__":
    main()