"""Tests for on-chain signal verification job."""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

import pytest

# Mock environment variables before imports
os.environ["ONCHAIN_VERIFICATION_DELAY_SEC"] = "180"
os.environ["ONCHAIN_VERIFICATION_TIMEOUT_SEC"] = "720"
os.environ["ONCHAIN_VERDICT_TTL_SEC"] = "900"
os.environ["BQ_ONCHAIN_FEATURES_VIEW"] = "project.dataset.view"
os.environ["ONCHAIN_RULES"] = "on"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"

from worker.jobs.onchain.verify_signal import (
    run_once,
    process_candidate,
    fetch_onchain_features,
    acquire_lock,
    metrics
)
from api.onchain.dto import Verdict


class TestVerifySignal:
    """Test suite for on-chain verification job."""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        db = Mock()
        db.execute = Mock()
        db.commit = Mock()
        db.rollback = Mock()
        return db
    
    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis_client = Mock()
        redis_client.set = Mock(return_value=True)
        return redis_client
    
    @pytest.fixture
    def mock_rules(self):
        """Mock rules configuration."""
        rules = Mock()
        rules.windows = [30, 60, 180]
        rules.thresholds = {
            'active_addr_pctl': {'high': 0.95},
            'growth_ratio': {'fast': 2.0},
            'top10_share': {'high_risk': 0.70},
            'self_loop_ratio': {'suspicious': 0.20}
        }
        return rules
    
    @pytest.fixture
    def mock_signal(self):
        """Mock signal record."""
        signal = Mock()
        signal.event_key = "eth:0x1234:1234567890"
        signal.state = "candidate"
        signal.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        signal.updated_at = datetime.now(timezone.utc)
        return signal
    
    def test_update_upgrade(self, mock_db, mock_redis, mock_rules, mock_signal):
        """Test upgrade verdict updates state to verified."""
        with patch('worker.jobs.onchain.verify_signal.fetch_onchain_features') as mock_fetch:
            with patch('worker.jobs.onchain.verify_signal.evaluate') as mock_eval:
                # Setup mocks
                mock_fetch.return_value = {
                    "active_addr_pctl": 0.96,
                    "growth_ratio": 2.5,
                    "top10_share": 0.3,
                    "self_loop_ratio": 0.05,
                    "asof_ts": datetime.now(timezone.utc).isoformat()
                }
                
                mock_eval.return_value = Verdict(
                    decision="upgrade",
                    confidence=1.0,
                    note=None
                )
                
                # Process candidate
                result = process_candidate(mock_db, mock_signal, mock_rules, mock_redis)
                
                # Verify
                assert result == "updated"
                assert mock_db.execute.call_count == 3  # UPDATE signals + INSERT signal_events
                assert mock_db.commit.called
                
                # Check state update
                update_call = mock_db.execute.call_args_list[0]
                assert "state = :state" in str(update_call)
                assert update_call[0][1]["state"] == "verified"
    
    def test_downgrade_priority(self, mock_db, mock_redis, mock_rules, mock_signal):
        """Test downgrade has priority over upgrade."""
        with patch('worker.jobs.onchain.verify_signal.fetch_onchain_features') as mock_fetch:
            with patch('worker.jobs.onchain.verify_signal.evaluate') as mock_eval:
                # Setup mocks
                mock_fetch.return_value = {
                    "active_addr_pctl": 0.96,
                    "growth_ratio": 2.5,
                    "top10_share": 0.75,
                    "self_loop_ratio": 0.25,
                    "asof_ts": datetime.now(timezone.utc).isoformat()
                }
                
                mock_eval.return_value = Verdict(
                    decision="downgrade",
                    confidence=1.0,
                    note=None
                )
                
                # Process candidate
                result = process_candidate(mock_db, mock_signal, mock_rules, mock_redis)
                
                # Verify
                assert result == "updated"
                update_call = mock_db.execute.call_args_list[0]
                assert update_call[0][1]["state"] == "rejected"
    
    def test_insufficient_no_state_change(self, mock_db, mock_redis, mock_rules, mock_signal):
        """Test insufficient verdict doesn't change state."""
        with patch('worker.jobs.onchain.verify_signal.fetch_onchain_features') as mock_fetch:
            with patch('worker.jobs.onchain.verify_signal.evaluate') as mock_eval:
                # Setup mocks
                mock_fetch.return_value = {
                    "active_addr_pctl": 0.5,
                    "growth_ratio": 1.0,
                    "top10_share": 0.3,
                    "self_loop_ratio": 0.05,
                    "asof_ts": datetime.now(timezone.utc).isoformat()
                }
                
                mock_eval.return_value = Verdict(
                    decision="insufficient",
                    confidence=0.0,
                    note="insufficient_evidence"
                )
                
                # Process candidate
                result = process_candidate(mock_db, mock_signal, mock_rules, mock_redis)
                
                # Verify
                assert result == "updated"
                update_call = mock_db.execute.call_args_list[0]
                # State should remain as candidate
                assert update_call[0][1]["state"] == "candidate"
                assert update_call[0][1]["confidence"] == Decimal("0")
    
    def test_evidence_delayed_timeout(self, mock_db, mock_redis, mock_rules, mock_signal):
        """Test timeout results in evidence_delayed event."""
        with patch('worker.jobs.onchain.verify_signal.fetch_onchain_features') as mock_fetch:
            # Setup mocks - no features returned
            mock_fetch.return_value = None
            
            # Process candidate
            result = process_candidate(mock_db, mock_signal, mock_rules, mock_redis)
            
            # Verify
            assert result == "updated"
            
            # Check event insertion
            event_call = mock_db.execute.call_args_list[0]
            assert "signal_events" in str(event_call)
            assert "evidence_delayed" in str(event_call)
            
            # Check confidence is 0
            update_call = mock_db.execute.call_args_list[1]
            assert "onchain_confidence = 0" in str(update_call)
    
    def test_idempotent_lock(self, mock_db, mock_redis, mock_rules, mock_signal):
        """Test Redis lock prevents duplicate processing."""
        # First call acquires lock
        mock_redis.set.return_value = True
        result1 = process_candidate(mock_db, mock_signal, mock_rules, mock_redis)
        
        # Second call fails to acquire lock
        mock_redis.set.return_value = False
        result2 = process_candidate(mock_db, mock_signal, mock_rules, mock_redis)
        
        assert result1 == "skipped"  # Skipped due to delay
        assert result2 == "skipped"  # Skipped due to lock
    
    def test_rules_off_flag(self, mock_db, mock_redis, mock_rules, mock_signal):
        """Test ONCHAIN_RULES=off only updates confidence."""
        with patch.dict(os.environ, {"ONCHAIN_RULES": "off"}):
            with patch('worker.jobs.onchain.verify_signal.fetch_onchain_features') as mock_fetch:
                with patch('worker.jobs.onchain.verify_signal.evaluate') as mock_eval:
                    # Reload module to pick up env change
                    import importlib
                    import worker.jobs.onchain.verify_signal as module
                    importlib.reload(module)
                    
                    # Setup mocks
                    mock_fetch.return_value = {
                        "active_addr_pctl": 0.96,
                        "growth_ratio": 2.5,
                        "top10_share": 0.3,
                        "self_loop_ratio": 0.05,
                        "asof_ts": datetime.now(timezone.utc).isoformat()
                    }
                    
                    mock_eval.return_value = Verdict(
                        decision="upgrade",
                        confidence=1.0,
                        note=None
                    )
                    
                    # Process candidate
                    result = module.process_candidate(mock_db, mock_signal, mock_rules, mock_redis)
                    
                    # Verify state unchanged
                    assert result == "updated"
                    update_call = mock_db.execute.call_args_list[0]
                    assert update_call[0][1]["state"] == "candidate"  # State not changed
    
    def test_bq_cost_metrics(self):
        """Test BigQuery cost metrics tracking."""
        with patch('worker.jobs.onchain.verify_signal.BQProvider') as mock_provider:
            # Setup mock
            mock_instance = mock_provider.return_value
            mock_instance.run_template.return_value = {
                "data": {
                    "active_addr_pctl": 0.5,
                    "asof_ts": datetime.now(timezone.utc).isoformat()
                },
                "metadata": {
                    "total_bytes_processed": 1048576  # 1MB
                }
            }
            
            # Clear metrics
            metrics["bq_query_count"] = 0
            metrics["bq_scanned_mb"] = 0.0
            
            # Fetch features
            result = fetch_onchain_features("eth", "0x1234", window_min=60)
            
            # Verify metrics
            assert metrics["bq_query_count"] == 1
            assert metrics["bq_scanned_mb"] == 1.0
    
    def test_skip_recent(self, mock_db, mock_redis, mock_rules):
        """Test recent candidates are skipped."""
        # Create very recent signal
        signal = Mock()
        signal.event_key = "eth:0x1234:1234567890"
        signal.state = "candidate"
        signal.created_at = datetime.now(timezone.utc) - timedelta(seconds=30)  # Only 30 seconds old
        
        # Process candidate
        result = process_candidate(mock_db, signal, mock_rules, mock_redis)
        
        # Verify skipped
        assert result == "skipped"
        assert not mock_db.execute.called
    
    @patch('worker.jobs.onchain.verify_signal.get_db')
    @patch('worker.jobs.onchain.verify_signal.load_rules')
    @patch('worker.jobs.onchain.verify_signal.get_redis_client')
    def test_run_once_stats(self, mock_redis_fn, mock_load_rules, mock_get_db):
        """Test run_once returns correct statistics."""
        # Setup mocks
        mock_redis_fn.return_value = Mock()
        mock_load_rules.return_value = Mock()
        
        # Mock database
        mock_db = Mock()
        mock_result = Mock()
        mock_result.fetchall.return_value = [
            Mock(event_key="eth:0x1:1", state="candidate", 
                 created_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                 updated_at=datetime.now(timezone.utc)),
            Mock(event_key="eth:0x2:2", state="candidate",
                 created_at=datetime.now(timezone.utc) - timedelta(seconds=30),
                 updated_at=datetime.now(timezone.utc))
        ]
        mock_db.execute.return_value = mock_result
        mock_get_db.return_value.__next__.return_value.__enter__.return_value = mock_db
        
        with patch('worker.jobs.onchain.verify_signal.process_candidate') as mock_process:
            mock_process.side_effect = ["updated", "skipped"]
            
            # Run
            stats = run_once(limit=10)
            
            # Verify stats
            assert stats["scanned"] == 2
            assert stats["evaluated"] == 2
            assert stats["updated"] == 1
            assert stats["skipped"] == 1
            assert stats["errors"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])