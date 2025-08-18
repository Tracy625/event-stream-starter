# BRIEF — MVP Product Summary

## What
A backend system that collects posts from fixed KOLs on X, filters and aggregates them into structured "events", runs quick risk/security checks, and pushes concise signal cards to Telegram. 
No trading features. Focus on accuracy, low latency, and low noise in signals.

## Users
Crypto hunters who need fast, structured signals with basic risk checks and heat momentum.

## MVP Scope (15 days)
- Fixed KOL monitoring on X (5–10 accounts), deduplicated.
- Filtering: rules + HF sentiment/keywords; mini-LLM structure.
- Event aggregation with `event_key`, evidence merge, heat snapshots (10m/30m).
- Security scan via GoPlus; DEX metrics via DexScreener/GeckoTerminal.
- Three-tier advice: observe / caution / opportunity.
- Telegram card push with dedup and `/detail`.

## Non-Goals
- Auto trading, multi-source expansion, custom candlesticks.

## Success
- P95 end-to-end ≤ 2 minutes; 3 known scam samples flagged red; hour-level dedup works.