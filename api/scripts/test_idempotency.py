#!/usr/bin/env python3
"""
Test script for idempotency module.

Usage:
    python api/scripts/test_idempotency.py
"""

import os
import sys
import time

# Add parent directory to path
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from api.core.idempotency import (
    cleanup_memory,
    clear_all,
    mark,
    mark_batch,
    reset_stats,
    seen,
    seen_batch,
    stats,
)


def test_basic_operations():
    """Test basic seen/mark operations"""
    print("\n=== Testing Basic Operations ===")

    # Clear any existing data
    clear_all()
    reset_stats()

    # Test single key operations
    key1 = "test_key_1"
    assert not seen(key1), f"Key {key1} should not exist initially"
    print(f"✓ Key '{key1}' not seen initially")

    mark(key1)
    assert seen(key1), f"Key {key1} should exist after marking"
    print(f"✓ Key '{key1}' marked and seen")

    # Test another key
    key2 = "test_key_2"
    assert not seen(key2), f"Key {key2} should not exist"
    mark(key2, ttl_seconds=60)  # Short TTL for testing
    assert seen(key2), f"Key {key2} should exist after marking"
    print(f"✓ Key '{key2}' marked with TTL and seen")

    return True


def test_batch_operations():
    """Test batch operations"""
    print("\n=== Testing Batch Operations ===")

    # Clear any existing data
    clear_all()
    reset_stats()

    keys = [f"batch_key_{i}" for i in range(5)]

    # Check batch - all should be unseen
    results = seen_batch(keys)
    assert all(not v for v in results.values()), "All keys should be unseen initially"
    print(f"✓ Batch check: all {len(keys)} keys unseen")

    # Mark first 3 keys
    mark_batch(keys[:3])
    results = seen_batch(keys)
    assert sum(results.values()) == 3, "Exactly 3 keys should be seen"
    print(f"✓ Marked 3 keys, batch check confirms")

    # Verify individual keys
    for i, key in enumerate(keys):
        expected = i < 3
        assert seen(key) == expected, f"Key {key} seen status incorrect"
    print(f"✓ Individual key checks match batch results")

    return True


def test_memory_cleanup():
    """Test memory cleanup mechanism"""
    print("\n=== Testing Memory Cleanup ===")

    # This only works in memory mode
    import api.core.idempotency as idem_module

    if idem_module._redis:
        print("⚠ Skipping memory cleanup test (Redis is available)")
        return True

    # Clear and reset
    clear_all()
    reset_stats()

    # Set a smaller max size for testing
    import api.core.idempotency as idem_module

    old_max_size = idem_module._MEMORY_MAX_SIZE
    idem_module._MEMORY_MAX_SIZE = 100  # Small size for testing

    # Add many keys to trigger cleanup
    max_size = 100  # Small size for testing
    for i in range(max_size + 50):
        mark(f"cleanup_key_{i}")
        time.sleep(0.001)  # Small delay to ensure different timestamps

    # Cleanup should have been triggered automatically
    current_stats = stats()
    memory_keys = current_stats.get("memory_keys", 0)
    assert (
        memory_keys <= max_size
    ), f"Memory keys ({memory_keys}) should be <= {max_size}"
    print(f"✓ Auto-cleanup triggered, keys reduced to {memory_keys}")

    # Restore original max size
    idem_module._MEMORY_MAX_SIZE = old_max_size

    # Manual cleanup test
    removed = cleanup_memory(50)
    current_stats = stats()
    memory_keys = current_stats.get("memory_keys", 0)
    assert (
        memory_keys <= 50
    ), f"Memory keys ({memory_keys}) should be <= 50 after manual cleanup"
    print(f"✓ Manual cleanup removed {removed} keys, {memory_keys} remaining")

    return True


def test_statistics():
    """Test statistics tracking"""
    print("\n=== Testing Statistics ===")

    # Clear and reset
    clear_all()
    reset_stats()

    # Perform some operations
    mark("stat_key_1")
    mark("stat_key_2")
    seen("stat_key_1")  # hit
    seen("stat_key_1")  # hit
    seen("stat_key_3")  # miss
    seen("stat_key_3")  # miss
    seen("stat_key_2")  # hit

    # Check stats
    current_stats = stats()
    assert current_stats["hits"] == 3, f"Expected 3 hits, got {current_stats['hits']}"
    assert (
        current_stats["misses"] == 2
    ), f"Expected 2 misses, got {current_stats['misses']}"
    assert (
        current_stats["marks"] == 2
    ), f"Expected 2 marks, got {current_stats['marks']}"

    hit_rate = current_stats["hit_rate"]
    expected_rate = 60.0  # 3 hits / 5 total * 100
    assert (
        abs(hit_rate - expected_rate) < 0.1
    ), f"Hit rate {hit_rate}% != expected {expected_rate}%"

    print(f"✓ Statistics tracking:")
    print(f"  - Backend: {current_stats['backend']}")
    print(f"  - Hits: {current_stats['hits']}")
    print(f"  - Misses: {current_stats['misses']}")
    print(f"  - Marks: {current_stats['marks']}")
    print(f"  - Hit rate: {hit_rate:.1f}%")

    if current_stats["backend"] == "redis":
        print(f"  - Redis available: {current_stats.get('redis_available', False)}")
    else:
        print(f"  - Memory keys: {current_stats.get('memory_keys', 'N/A')}")
        print(f"  - Memory max size: {current_stats.get('memory_max_size', 'N/A')}")

    return True


def test_clear_operations():
    """Test clear operations"""
    print("\n=== Testing Clear Operations ===")

    # Add some keys
    for i in range(10):
        mark(f"clear_key_{i}")

    # Verify they exist
    assert seen("clear_key_0"), "Keys should exist before clear"
    assert seen("clear_key_9"), "Keys should exist before clear"

    # Clear all
    count = clear_all()
    print(f"✓ Cleared {count} keys")

    # Verify they're gone
    assert not seen("clear_key_0"), "Keys should not exist after clear"
    assert not seen("clear_key_9"), "Keys should not exist after clear"

    # Stats should still work
    current_stats = stats()
    if current_stats["backend"] == "redis":
        # Just verify Redis is still available
        assert current_stats.get("redis_available", False), "Redis should be available"
    else:
        assert current_stats.get("memory_keys", 0) == 0, "No memory keys should remain"

    print("✓ All keys cleared successfully")

    return True


def main():
    """Run all tests"""
    print("Testing Idempotency Module")
    print("=" * 50)

    # Check backend
    import api.core.idempotency as idem_module

    backend = "Redis" if idem_module._redis else "Memory"
    print(f"Using backend: {backend}")

    tests = [
        ("Basic Operations", test_basic_operations),
        ("Batch Operations", test_batch_operations),
        ("Memory Cleanup", test_memory_cleanup),
        ("Statistics", test_statistics),
        ("Clear Operations", test_clear_operations),
    ]

    failed = []
    for name, test_func in tests:
        try:
            if test_func():
                print(f"✅ {name} passed")
            else:
                print(f"❌ {name} failed")
                failed.append(name)
        except Exception as e:
            print(f"❌ {name} failed with error: {e}")
            failed.append(name)

    print("\n" + "=" * 50)
    if failed:
        print(f"❌ {len(failed)} test(s) failed: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("✅ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
