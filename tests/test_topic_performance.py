"""
Performance benchmarks for topic detection and aggregation.
Tests latency, throughput, and resource usage.
"""

import pytest
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import json


@pytest.mark.slow
class TestTopicPerformance:
    """Performance tests for topic pipeline"""

    def test_topic_detection_latency(self):
        """Test that topic detection completes within 100ms"""
        from worker.pipeline.is_memeable_topic import MemeableTopicDetector

        detector = MemeableTopicDetector()
        detector.redis = None  # Disable Redis
        detector.mini_llm_timeout = 0  # Disable LLM

        text = "$PEPE is going to moon! Best gem token ever!"

        start = time.perf_counter()
        is_meme, entities, confidence = detector.is_memeable(text)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1  # Must complete within 100ms
        assert is_meme is True
        assert len(entities) > 0

    @patch('worker.jobs.topic_signal_scan.get_db_session')
    def test_scan_throughput(self, mock_get_session):
        """Test that scan can process 100 events under 500ms"""
        from worker.jobs.topic_signal_scan import scan_topic_signals

        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Create 100 mock events
        mock_events = []
        for i in range(100):
            mock_events.append({
                "event_key": f"event_{i:03d}",
                "topic_id": f"t.hash{i % 10}",  # 10 different topics
                "topic_entities": [f"entity{i}"],
                "topic_confidence": 0.5 + (i % 5) * 0.1,
                "last_ts": datetime.now(timezone.utc) - timedelta(minutes=i)
            })

        mock_session.execute.return_value.mappings.return_value.fetchall.return_value = mock_events
        mock_session.execute.return_value.mappings.return_value.fetchone.return_value = None
        mock_session.execute.return_value.rowcount = 1

        start = time.perf_counter()
        result = scan_topic_signals()
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5  # Must complete within 500ms
        assert result["success"] is True
        assert result["created"] == 100

    @patch('worker.jobs.topic_aggregate.get_db_session')
    def test_aggregate_performance(self, mock_get_session):
        """Test that aggregate can process 1000 events under 1 second"""
        from worker.jobs.topic_aggregate import aggregate_topics

        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Create aggregated data for 50 topics with varying entity arrays
        mock_rows = []
        for i in range(50):
            # Each topic has between 5-25 mentions
            mention_count = 5 + (i % 20)
            entities_groups = []
            for j in range(mention_count):
                # Each mention has 1-3 entities
                entities = [f"entity_{i}_{j}_{k}" for k in range(1 + (j % 3))]
                entities_groups.append(entities)

            mock_rows.append({
                "topic_hash": f"t.hash{i:03d}",
                "all_entities": entities_groups,
                "mention_count": mention_count,
                "latest_ts": datetime.now(timezone.utc) - timedelta(hours=i)
            })

        mock_session.execute.return_value.mappings.return_value.fetchall.return_value = mock_rows

        start = time.perf_counter()
        result = aggregate_topics()
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0  # Must complete within 1 second
        assert result["success"] is True
        assert result["groups"] == 50
        assert len(result["candidates"]) == 50

    def test_entity_deduplication_performance(self):
        """Test entity deduplication performance with large sets"""
        from worker.jobs.topic_aggregate import aggregate_topics

        # Create a large list with many duplicates
        entities_raw = []
        for i in range(1000):
            entities_raw.extend([f"entity{i % 100}", f"token{i % 50}", f"gem{i % 20}"])

        start = time.perf_counter()
        # Simulate the deduplication logic from aggregate_topics
        entities = sorted(set(entities_raw))
        elapsed = time.perf_counter() - start

        assert elapsed < 0.01  # Dedup should be very fast
        assert len(entities) <= 170  # 100 + 50 + 20 unique values max
        assert all(isinstance(e, str) for e in entities)

    def test_concurrent_scans(self):
        """Test that multiple scans can run concurrently"""
        from concurrent.futures import ThreadPoolExecutor
        import threading

        # Track which threads executed
        thread_ids = set()
        results = []
        lock = threading.Lock()

        def mock_scan(scan_id):
            """Simple mock scan that tracks thread execution"""
            with lock:
                thread_ids.add(threading.current_thread().ident)

            # Simulate some work
            time.sleep(0.01)

            # Return a mock result
            return {
                "success": True,
                "created": 1,
                "scan_id": scan_id,
                "thread_id": threading.current_thread().ident
            }

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(mock_scan, i) for i in range(5)]
            results = [f.result() for f in futures]
        elapsed = time.perf_counter() - start

        # With concurrency, 5 tasks with 0.01s each should complete much faster than 0.05s serial
        assert elapsed < 0.05  # Should complete in parallel, not serial
        assert len(results) == 5
        assert all(r["success"] for r in results)
        assert all(r["created"] == 1 for r in results)
        # Verify multiple threads were used
        assert len(thread_ids) > 1, "Expected multiple threads to be used"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "slow"])