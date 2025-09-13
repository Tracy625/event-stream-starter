"""Basic metrics tests without network calls"""
import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
import sys
import os

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.core import metrics
from api.core import tracing


def test_telegram_metrics(monkeypatch):
    """Test telegram metrics collection"""
    
    # Clear registry
    metrics._registry.clear()
    
    # Capture printed logs
    captured_logs = []
    
    def mock_print(*args, **kwargs):
        if args:
            captured_logs.append(args[0])
    
    monkeypatch.setattr("builtins.print", mock_print)
    
    # Import telegram module
    from api.services import telegram
    
    # Create notifier
    notifier = telegram.TelegramNotifier()
    # Set fake token to avoid business logic failure due to missing token
    notifier.bot_token = "test-token"
    
    # Mock responses for different scenarios
    def mock_post_200(*args, **kwargs):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "ok": True,
            "result": {"message_id": 12345}
        }
        return response
    
    def mock_post_429(*args, **kwargs):
        response = Mock()
        response.status_code = 429
        response.json.return_value = {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests"
        }
        return response
    
    def mock_post_network_error(*args, **kwargs):
        import requests
        raise requests.exceptions.RequestException("Network error")
    
    # Test 1: Successful send (200)
    with patch("requests.post", mock_post_200):
        result = notifier.send_message(
            chat_id="test_chat",
            text="Test message",
            event_key="test_event_1",
            attempt=1
        )
        assert result["success"] is True
    
    # Test 2: Rate limit (429)
    with patch("requests.post", mock_post_429):
        result = notifier.send_message(
            chat_id="test_chat",
            text="Test message",
            event_key="test_event_2",
            attempt=2
        )
        assert result["success"] is False
    
    # Test 3: Network error
    with patch("requests.post", mock_post_network_error):
        result = notifier.send_message(
            chat_id="test_chat",
            text="Test message",
            event_key="test_event_3",
            attempt=3
        )
        assert result["success"] is False
    
    # Export metrics
    export = metrics.export_text()
    
    # Assert metrics
    assert 'telegram_error_code_count{code="200"} 1' in export
    assert 'telegram_error_code_count{code="429"} 1' in export
    assert 'telegram_error_code_count{code="net"} 1' in export
    assert 'telegram_send_latency_ms_count' in export
    
    # Check logs contain trace_id (only count structured 'telegram.send' logs)
    send_logs = []
    for log in captured_logs:
        s = str(log).strip()
        if not s.startswith("{"):
            continue
        try:
            d = json.loads(s)
        except json.JSONDecodeError:
            continue
        if d.get("evt") == "telegram.send":
            send_logs.append(d)

    # Expect exactly 3 send logs (200, 429, net)
    assert len(send_logs) == 3
    for d in send_logs:
        assert "trace_id" in d
        assert d["evt"] == "telegram.send"


def test_trace_id_propagation():
    """Test trace ID propagation through context"""
    
    # Set trace ID
    test_trace_id = "test-trace-123"
    tracing.set_trace_id(test_trace_id)
    
    # Verify it's set
    assert tracing.get_trace_id() == test_trace_id
    
    # Test context manager
    with tracing.trace_ctx("another-trace-456") as tid:
        assert tid == "another-trace-456"
        assert tracing.get_trace_id() == "another-trace-456"
    
    # Should restore original
    assert tracing.get_trace_id() == test_trace_id


def test_outbox_backlog_metric(monkeypatch):
    """Test outbox backlog gauge metric"""
    
    # Clear registry
    metrics._registry.clear()
    
    # Mock count_backlog to return 123
    def mock_count_backlog(session):
        return 123
    
    # Create mock session
    mock_session = Mock()
    
    # Patch the outbox_repo module
    mock_repo = Mock()
    mock_repo.count_backlog = mock_count_backlog
    mock_repo.dequeue_batch = Mock(return_value=[])
    
    sys.modules['api.db.repositories.outbox_repo'] = mock_repo
    sys.modules['api.db.repositories'] = Mock(outbox_repo=mock_repo)
    
    # Import and run the job
    from worker.jobs import outbox_retry
    
    # Process batch
    outbox_retry.process_outbox_batch(mock_session)
    
    # Export metrics
    export = metrics.export_text()
    
    # Assert backlog metric
    assert 'outbox_backlog 123' in export


def test_pipeline_latency_metric():
    """Test pipeline latency histogram"""
    
    # Clear registry
    metrics._registry.clear()
    
    # Get histogram
    hist = metrics.histogram(
        "pipeline_latency_ms",
        "Pipeline latency",
        [50, 100, 200, 500, 1000, 2000, 5000]
    )
    
    # Record some observations
    hist.observe(75.5)
    hist.observe(150.2)
    hist.observe(450.8)
    hist.observe(1200.3)
    
    # Export metrics
    export = metrics.export_text()
    
    # Assert histogram metrics
    assert 'pipeline_latency_ms_bucket{le="50"} 0' in export
    assert 'pipeline_latency_ms_bucket{le="100"} 1' in export
    assert 'pipeline_latency_ms_bucket{le="200"} 2' in export
    assert 'pipeline_latency_ms_bucket{le="500"} 3' in export
    assert 'pipeline_latency_ms_bucket{le="1000"} 3' in export
    assert 'pipeline_latency_ms_bucket{le="2000"} 4' in export
    assert 'pipeline_latency_ms_count 4' in export


def test_cards_send_route():
    """Test cards send route with tracing"""
    
    # Clear registry
    metrics._registry.clear()
    
    # Import route
    from api.routes import cards_send
    
    # Create mock request
    mock_request = Mock()
    
    # Test with header trace ID
    import asyncio
    result = asyncio.run(
        cards_send.send_card(
            request=mock_request,
            data={"test": "data"},
            trace_id="header-trace-123",
            trace_id_query=None
        )
    )
    
    assert result["success"] is True
    assert result["trace_id"] == "header-trace-123"
    
    # Export metrics
    export = metrics.export_text()
    
    # Should have recorded pipeline latency
    assert 'pipeline_latency_ms_count 1' in export


if __name__ == "__main__":
    test_telegram_metrics(pytest.MonkeyPatch())
    test_trace_id_propagation()
    test_outbox_backlog_metric(pytest.MonkeyPatch())
    test_pipeline_latency_metric()
    test_cards_send_route()
    print("All tests passed!")