"""
Unit tests for topic detection and signal generation.
Uses mocks to test business logic without database dependencies.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, call, patch

import pytest


class TestTopicDetection:
    """Test MemeableTopicDetector logic with mocks"""

    def test_is_memeable_with_entities(self):
        """Test topic detection returns correct entities"""
        from worker.pipeline.is_memeable_topic import MemeableTopicDetector

        detector = MemeableTopicDetector()
        detector.redis = None  # Disable Redis for unit test
        detector.mini_llm_timeout = 0  # Disable LLM verification

        text = "Just bought $PEPE token, this is the next moon gem!"
        is_meme, entities, confidence = detector.is_memeable(text)

        assert is_meme is True
        assert "pepe" in [e.lower() for e in entities]
        assert confidence > 0

    def test_is_memeable_without_entities(self):
        """Test non-memeable text returns False"""
        from worker.pipeline.is_memeable_topic import MemeableTopicDetector

        detector = MemeableTopicDetector()
        detector.redis = None
        detector.mini_llm_timeout = 0

        text = "The weather is nice today"
        is_meme, entities, confidence = detector.is_memeable(text)

        assert is_meme is False
        assert len(entities) == 0


class TestTopicSignalScan:
    """Test scan_topic_signals with mocked database"""

    @patch("worker.jobs.topic_signal_scan.get_db_session")
    def test_scan_creates_new_signals(self, mock_get_session):
        """Test that scan creates signals for events with topics"""
        from worker.jobs.topic_signal_scan import scan_topic_signals

        # Mock session and query results
        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock events with topic data
        mock_events = [
            {
                "event_key": "event_001",
                "topic_id": "t.abc123",
                "topic_entities": ["pepe", "gem"],
                "topic_confidence": 0.8,
                "last_ts": datetime.now(timezone.utc),
            }
        ]

        # Setup execute() to return different results for different queries
        # First call: SELECT events (returns mock_events)
        # Second call: SELECT existing signal (returns None)
        # Third call: INSERT (returns mock with rowcount)

        mock_mappings_fetchall = MagicMock()
        mock_mappings_fetchall.fetchall.return_value = mock_events

        mock_mappings_fetchone = MagicMock()
        mock_mappings_fetchone.fetchone.return_value = None

        mock_insert_result = MagicMock()
        mock_insert_result.rowcount = 1

        # Configure execute to return appropriate mock based on call count
        mock_session.execute.side_effect = [
            MagicMock(
                mappings=MagicMock(return_value=mock_mappings_fetchall)
            ),  # SELECT events
            MagicMock(
                mappings=MagicMock(return_value=mock_mappings_fetchone)
            ),  # SELECT existing signal
            mock_insert_result,  # INSERT
        ]

        result = scan_topic_signals()

        assert result["success"] is True
        assert result["created"] == 1
        assert result["updated"] == 0

        # Verify execute was called 3 times (SELECT events, CHECK existing, INSERT)
        assert mock_session.execute.call_count == 3

        # Verify commit was called
        mock_session.commit.assert_called_once()

    @patch("worker.jobs.topic_signal_scan.get_db_session")
    def test_scan_skips_non_topic_signals(self, mock_get_session):
        """Test that scan skips events with non-topic signals"""
        from worker.jobs.topic_signal_scan import scan_topic_signals

        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_events = [
            {
                "event_key": "event_002",
                "topic_id": "t.xyz789",
                "topic_entities": ["arb"],
                "topic_confidence": 0.6,
                "last_ts": datetime.now(timezone.utc),
            }
        ]

        # Existing non-topic signal
        existing_signal = {"id": 1, "market_type": "risk"}

        mock_session.execute.return_value.mappings.return_value.fetchall.return_value = (
            mock_events
        )
        mock_session.execute.return_value.mappings.return_value.fetchone.return_value = (
            existing_signal
        )

        result = scan_topic_signals()

        assert result["success"] is True
        assert result["created"] == 0
        assert result["skipped_non_topic"] == 1

        # Verify no INSERT was attempted
        mock_session.commit.assert_called_once()


class TestTopicAggregate:
    """Test aggregate_topics with mocked database"""

    @patch("worker.jobs.topic_aggregate.get_db_session")
    def test_aggregate_flattens_entities(self, mock_get_session):
        """Test that aggregate correctly flattens entity arrays"""
        from worker.jobs.topic_aggregate import aggregate_topics

        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        # Mock aggregated data with nested arrays
        mock_rows = [
            {
                "topic_hash": "t.hash1",
                "all_entities": [["pepe"], ["pepe", "gem"], ["gem"]],  # Nested arrays
                "mention_count": 3,
                "latest_ts": datetime.now(timezone.utc),
            }
        ]

        mock_session.execute.return_value.mappings.return_value.fetchall.return_value = (
            mock_rows
        )

        result = aggregate_topics()

        assert result["success"] is True
        assert result["groups"] == 1
        assert len(result["candidates"]) == 1

        candidate = result["candidates"][0]
        assert candidate["topic_id"] == "t.hash1"
        assert set(candidate["entities"]) == {"gem", "pepe"}  # Flattened and deduped
        assert candidate["mention_count"] == 3

    @patch("worker.jobs.topic_aggregate.get_db_session")
    def test_aggregate_handles_null_entities(self, mock_get_session):
        """Test that aggregate handles NULL entities gracefully"""
        from worker.jobs.topic_aggregate import aggregate_topics

        mock_session = MagicMock()
        mock_get_session.return_value = mock_session

        mock_rows = [
            {
                "topic_hash": "t.hash2",
                "all_entities": None,  # NULL from database
                "mention_count": 1,
                "latest_ts": datetime.now(timezone.utc),
            }
        ]

        mock_session.execute.return_value.mappings.return_value.fetchall.return_value = (
            mock_rows
        )

        result = aggregate_topics()

        assert result["success"] is True
        assert result["empty_entities_groups"] == 1
        assert len(result["candidates"]) == 0  # Skipped due to empty entities


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
