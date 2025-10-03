# Sample Data

This directory contains fake sample data for testing and demonstration purposes.

## Files

### `events.json`
Contains 10 example events representing different types of crypto signals:

1. **Token Listing** - Exchange listing announcement
2. **Token Launch** - New token on Pump.fun
3. **Security Alert** - Honeypot/scam detection
4. **Protocol Update** - DeFi protocol upgrade
5. **Whale Activity** - Large wallet transfers
6. **NFT Collection** - NFT launch announcement
7. **Airdrop** - Token distribution announcement
8. **Depeg Alert** - Stablecoin price deviation
9. **Trending Topic** - Social media viral token
10. **Partnership** - Strategic collaboration announcement

**Event Structure:**
```json
{
  "id": "evt_001",
  "event_key": "chain:SYMBOL:timestamp",
  "type": "event_type",
  "symbol": "TOKEN",
  "token_ca": "contract_address",
  "chain": "ethereum|solana|bsc|arbitrum",
  "claim": {
    "actor": "who",
    "predicate": "what",
    "object": "context",
    "confidence": 0.0-1.0
  },
  "evidence": [
    {
      "type": "evidence_type",
      "source": "data_source",
      "...": "source_specific_fields"
    }
  ],
  "sentiment_score": -1.0 to 1.0,
  "risk_flags": ["flag1", "flag2"],
  "created_at": "ISO8601_timestamp"
}
```

### `posts.json`
Contains 15 example social media posts from various sources:

- KOL tweets about tokens
- Whale watching alerts
- Security warnings
- Market analysis
- News announcements
- Airdrop information

**Post Structure:**
```json
{
  "id": "post_001",
  "source": "twitter",
  "author": "username",
  "text": "post content",
  "timestamp": "ISO8601_timestamp",
  "urls": ["url1", "url2"],
  "mentions": ["TOKEN1", "TOKEN2"],
  "token_ca": "contract_address_or_null",
  "symbol": "SYMBOL_or_null",
  "is_candidate": true|false
}
```

## Usage

### Testing Pipeline
```python
import json

# Load sample events
with open('samples/events.json') as f:
    events = json.load(f)

# Process through your pipeline
for event in events:
    process_event(event)
```

### Demo Mode
Set environment variable to use sample data:
```bash
DEMO_MODE=true
SAMPLE_DATA_PATH=samples/
```

### Integration Tests
```python
import pytest
from pathlib import Path

@pytest.fixture
def sample_events():
    path = Path(__file__).parent / 'samples' / 'events.json'
    return json.loads(path.read_text())

def test_event_processing(sample_events):
    for event in sample_events:
        result = process_event(event)
        assert result.is_valid()
```

## Data Characteristics

### Chains Represented
- Ethereum (ETH) - 7 events
- Solana (SOL) - 2 events
- Binance Smart Chain (BSC) - 1 event
- Arbitrum (ARB) - 1 event

### Event Types
- `token_listing` - Exchange listings
- `token_launch` - New token launches
- `security_alert` - Scam/honeypot warnings
- `protocol_update` - Protocol upgrades
- `whale_activity` - Large transfers
- `nft_collection` - NFT drops
- `airdrop_announcement` - Token distributions
- `depeg_alert` - Stablecoin deviations
- `trending_topic` - Viral mentions
- `partnership_announcement` - Collaborations

### Evidence Types
- `SOCIAL_POST` - Twitter/social media
- `DEX_DATA` - DEX liquidity/price data
- `ONCHAIN_EVENT` - Blockchain events
- `SECURITY_SCAN` - Security check results
- `SECOND_SOURCE` - Confirming sources
- `SOCIAL_TREND` - Aggregated social metrics

### Risk Scenarios
Sample data includes:
- ✅ Safe tokens with positive signals
- ⚠️ Medium risk tokens (low liquidity, unverified)
- 🚨 High risk tokens (honeypot, high tax, depeg)

## Extending Sample Data

To add more samples:

1. Follow the JSON structure above
2. Use realistic but fake data
3. Include diverse scenarios
4. Test edge cases
5. Document any new fields

## Notes

- All addresses are fake/example addresses
- All usernames are prefixed with `demo_`
- All timestamps are in ISO8601 UTC format
- Sentiment scores range from -1.0 (negative) to 1.0 (positive)
- Confidence scores range from 0.0 (low) to 1.0 (high)

**These are NOT real trading signals. Do not use for actual trading decisions.**
