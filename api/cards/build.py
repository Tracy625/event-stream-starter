"""
Day19 Card Builder - Assembles data from multiple sources into schema-compliant cards
"""

import re
import json
import logging
import jsonschema
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, List, Any

from api.cards.summarizer import summarize_card


def _validate_event_key(event_key: str) -> None:
    """Validate event_key format"""
    if not event_key or not isinstance(event_key, str):
        raise ValueError("invalid event_key: empty or not string")
    
    # Pattern from cards.schema.json (uppercase only)
    pattern = r"^[A-Z0-9:_\-\.]{8,128}$"
    if not re.match(pattern, event_key):
        raise ValueError(f"invalid event_key: does not match pattern {pattern}")


def _get_goplus_data(event_key: str) -> Optional[Dict]:
    """Fetch GoPlus security data"""
    try:
        # Try to import and use existing provider
        # First attempt: goplus_provider
        try:
            from api.providers.goplus_provider import get_latest
            return get_latest(event_key)
        except ImportError:
            pass
        
        # Second attempt: security provider
        try:
            from api.services.security import get_goplus_data
            return get_goplus_data(event_key)
        except ImportError:
            pass
        
        # Third attempt: direct goplus module
        try:
            from api.jobs.goplus_scan import get_token_security
            # Extract token address from event_key if needed
            if ":" in event_key:
                parts = event_key.split(":")
                if len(parts) >= 3:
                    address = parts[2]
                    return get_token_security("eth", address)
        except ImportError:
            pass
        
        return None
    except Exception:
        return None


def _get_dex_data(event_key: str) -> Optional[Dict]:
    """Fetch DEX market data"""
    try:
        # Try to import and use existing provider
        try:
            from api.providers.dex_provider import get_latest
            return get_latest(event_key)
        except ImportError:
            pass
        
        # Alternative: dex service
        try:
            from api.services.dex import get_dex_data
            return get_dex_data(event_key)
        except ImportError:
            pass
        
        return None
    except Exception:
        return None


def _get_onchain_data(event_key: str) -> Optional[Dict]:
    """Fetch on-chain features snapshot"""
    try:
        # Try to import and use existing provider
        try:
            from api.providers.onchain_provider import get_snapshot
            return get_snapshot(event_key)
        except ImportError:
            pass
        
        # Alternative: onchain service
        try:
            from api.services.onchain import get_features
            return get_features(event_key)
        except ImportError:
            pass
        
        return None
    except Exception:
        return None


def _get_rules_data(event_key: str) -> Optional[Dict]:
    """Fetch rules evaluation results"""
    try:
        # Try Day18 rules evaluator
        try:
            from api.rules.evaluator import get_rules
            return get_rules(event_key)
        except ImportError:
            pass
        
        # Alternative: rules engine
        try:
            from api.rules import evaluate
            return evaluate(event_key)
        except ImportError:
            pass
        
        return None
    except Exception:
        return None


def _get_evidence_data(event_key: str) -> Optional[List[Dict]]:
    """Fetch evidence/summary data"""
    try:
        # Try evidence store
        try:
            from api.evidence.store import get_by_event
            return get_by_event(event_key)
        except ImportError:
            pass
        
        # Alternative: evidence service
        try:
            from api.services.evidence import get_evidence
            return get_evidence(event_key)
        except ImportError:
            pass
        
        return None
    except Exception:
        return None


def _extract_timestamp(data: Dict, field_names: List[str]) -> Optional[str]:
    """Extract timestamp from data using possible field names"""
    for field in field_names:
        if field in data:
            val = data[field]
            if isinstance(val, str):
                return val
            elif hasattr(val, 'isoformat'):
                return val.isoformat() + 'Z'
    return None


def _get_oldest_timestamp(sources: List[Optional[Dict]]) -> str:
    """Get oldest timestamp from all sources or current time"""
    timestamps = []
    
    for source in sources:
        if source:
            ts = _extract_timestamp(source, ['as_of', 'ts', 'updated_at', 'created_at', 'timestamp'])
            if ts:
                timestamps.append(ts)
    
    if timestamps:
        # Return oldest (min) timestamp
        return min(timestamps)
    
    # No timestamps found, return current time
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _build_goplus_section(goplus_data: Optional[Dict]) -> Optional[Dict]:
    """Build data.goplus section from raw goplus data"""
    if not goplus_data:
        return None
    
    section = {}
    
    # Map risk level
    if 'risk' in goplus_data:
        section['risk'] = goplus_data['risk']
    elif 'risk_level' in goplus_data:
        section['risk'] = goplus_data['risk_level']
    else:
        section['risk'] = 'gray'
    
    # Ensure risk is valid enum
    if section['risk'] not in ['green', 'yellow', 'red', 'gray']:
        section['risk'] = 'gray'
    
    # Map source
    if 'source' in goplus_data:
        section['risk_source'] = goplus_data['source']
    elif 'provider' in goplus_data:
        section['risk_source'] = goplus_data['provider']
    else:
        section['risk_source'] = 'GoPlus@v1.0'
    
    # Optional fields
    if 'buy_tax' in goplus_data:
        section['tax_buy'] = float(goplus_data['buy_tax'])
    if 'sell_tax' in goplus_data:
        section['tax_sell'] = float(goplus_data['sell_tax'])
    if 'lp_locked' in goplus_data:
        section['lp_locked'] = bool(goplus_data['lp_locked'])
    if 'is_honeypot' in goplus_data:
        section['honeypot'] = bool(goplus_data['is_honeypot'])
    elif 'honeypot' in goplus_data:
        section['honeypot'] = bool(goplus_data['honeypot'])
    
    # Diagnostic info if available
    diagnostic = {}
    if 'source_type' in goplus_data:
        diagnostic['source'] = goplus_data['source_type']
    if 'from_cache' in goplus_data:
        diagnostic['cache'] = bool(goplus_data['from_cache'])
    if 'is_stale' in goplus_data:
        diagnostic['stale'] = bool(goplus_data['is_stale'])
    if 'degraded' in goplus_data:
        diagnostic['degrade'] = bool(goplus_data['degraded'])
    
    if diagnostic:
        section['diagnostic'] = diagnostic
    
    return section


def _build_dex_section(dex_data: Optional[Dict]) -> Optional[Dict]:
    """Build data.dex section from raw dex data"""
    if not dex_data:
        return None
    
    section = {}
    
    # Price
    if 'price_usd' in dex_data:
        section['price_usd'] = float(dex_data['price_usd'])
    elif 'price' in dex_data:
        section['price_usd'] = float(dex_data['price'])
    
    # Liquidity
    if 'liquidity_usd' in dex_data:
        section['liquidity_usd'] = float(dex_data['liquidity_usd'])
    elif 'liquidity' in dex_data:
        section['liquidity_usd'] = float(dex_data['liquidity'])
    
    # FDV
    if 'fdv' in dex_data:
        section['fdv'] = float(dex_data['fdv'])
    elif 'market_cap' in dex_data:
        section['fdv'] = float(dex_data['market_cap'])
    
    # OHLC data
    ohlc = {}
    for timeframe in ['m5', 'm15', 'h1']:
        if timeframe in dex_data:
            frame_data = dex_data[timeframe]
            if isinstance(frame_data, dict) and all(k in frame_data for k in ['open', 'high', 'low', 'close']):
                ohlc[timeframe] = {
                    'open': float(frame_data['open']),
                    'high': float(frame_data['high']),
                    'low': float(frame_data['low']),
                    'close': float(frame_data['close']),
                    'ts': frame_data.get('ts', datetime.now(timezone.utc).isoformat() + 'Z')
                }
    
    if ohlc:
        section['ohlc'] = ohlc
    
    # Diagnostic info
    diagnostic = {}
    if 'source_type' in dex_data:
        diagnostic['source'] = dex_data['source_type']
    if 'from_cache' in dex_data:
        diagnostic['cache'] = bool(dex_data['from_cache'])
    if 'is_stale' in dex_data:
        diagnostic['stale'] = bool(dex_data['is_stale'])
    if 'degraded' in dex_data:
        diagnostic['degrade'] = bool(dex_data['degraded'])
    
    if diagnostic:
        section['diagnostic'] = diagnostic
    
    return section if section else None


def _build_onchain_section(onchain_data: Optional[Dict]) -> Optional[Dict]:
    """Build data.onchain section from raw onchain data"""
    if not onchain_data:
        return None
    
    section = {}
    
    # Features snapshot
    if 'features_snapshot' in onchain_data:
        section['features_snapshot'] = onchain_data['features_snapshot']
    elif 'features' in onchain_data:
        section['features_snapshot'] = onchain_data['features']
    
    # Source level
    if 'source_level' in onchain_data:
        section['source_level'] = onchain_data['source_level']
    
    # Only return if we have at least one field
    return section if section else None


def _build_rules_section(rules_data: Optional[Dict], degrade_reasons: List[str]) -> Dict:
    """Build rules section from raw rules data"""
    if not rules_data:
        # Default when missing
        section = {
            'level': 'none',
            'reasons': degrade_reasons[:3] if degrade_reasons else []
        }
    else:
        section = {}
        
        # Level (required)
        if 'level' in rules_data:
            section['level'] = rules_data['level']
        elif 'risk_level' in rules_data:
            section['level'] = rules_data['risk_level']
        else:
            section['level'] = 'none'
        
        # Ensure valid enum
        if section['level'] not in ['none', 'watch', 'caution', 'risk']:
            section['level'] = 'none'
        
        # Score (optional)
        if 'score' in rules_data:
            section['score'] = float(rules_data['score'])
        
        # Reasons (max 3)
        reasons = []
        if 'reasons' in rules_data and isinstance(rules_data['reasons'], list):
            reasons = rules_data['reasons'][:3]
        
        # Add degrade reasons if space available
        for reason in degrade_reasons:
            if len(reasons) < 3:
                reasons.append(reason)
        
        if reasons:
            section['reasons'] = reasons
        
        # All reasons (max 20)
        if 'all_reasons' in rules_data and isinstance(rules_data['all_reasons'], list):
            section['all_reasons'] = rules_data['all_reasons'][:20]
    
    return section


def _build_evidence_section(evidence_data: Optional[List[Dict]]) -> Optional[List[Dict]]:
    """Build evidence section from raw evidence data"""
    if not evidence_data:
        return None
    
    evidence = []
    for item in evidence_data:
        if isinstance(item, dict):
            ev = {}
            
            # Type (required)
            if 'type' in item:
                ev['type'] = str(item['type'])[:32]
            elif 'category' in item:
                ev['type'] = str(item['category'])[:32]
            else:
                ev['type'] = 'unknown'
            
            # Description (required)
            if 'desc' in item:
                ev['desc'] = str(item['desc'])[:240]
            elif 'description' in item:
                ev['desc'] = str(item['description'])[:240]
            elif 'text' in item:
                ev['desc'] = str(item['text'])[:240]
            else:
                ev['desc'] = 'No description'
            
            # URL (optional)
            if 'url' in item:
                ev['url'] = str(item['url'])
            elif 'link' in item:
                ev['url'] = str(item['link'])
            
            evidence.append(ev)
    
    return evidence if evidence else None


def _render_card(card: Dict) -> Optional[Dict]:
    """Try to render card for Telegram and UI"""
    rendered = {}
    
    # Try Telegram rendering
    try:
        from api.renderers.cards import tg_render
        tg_text = tg_render(card)
        if tg_text:
            rendered['tg'] = str(tg_text)[:4096]
    except ImportError:
        pass
    except Exception:
        pass
    
    # Try UI rendering
    try:
        from api.renderers.cards import ui_render
        ui_html = ui_render(card)
        if ui_html:
            rendered['ui'] = str(ui_html)[:8192]
    except ImportError:
        pass
    except Exception:
        pass
    
    return rendered if rendered else None


def _load_schema() -> Dict:
    """Load the cards schema"""
    schema_path = Path(__file__).parent.parent.parent / "schemas" / "cards.schema.json"
    with open(schema_path) as f:
        return json.load(f)


def build_card(event_key: str, render: bool = False) -> Dict:
    """
    Build a schema-compliant card from multiple data sources
    
    Args:
        event_key: Event identifier
        render: Whether to render tg/ui templates
        
    Returns:
        dict: Schema-compliant card object
        
    Raises:
        ValueError: If event_key is invalid or no usable sources
    """
    # Validate event_key
    _validate_event_key(event_key)
    
    # Initialize card structure
    card = {
        'event_key': event_key
    }
    
    # Fetch all data sources
    goplus_data = _get_goplus_data(event_key)
    dex_data = _get_dex_data(event_key)
    onchain_data = _get_onchain_data(event_key)
    rules_data = _get_rules_data(event_key)
    evidence_data = _get_evidence_data(event_key)
    
    # Track degradation
    degrade = False
    degrade_reasons = []
    
    # Build data sections
    data = {}
    
    # GoPlus section (required by schema)
    goplus_section = _build_goplus_section(goplus_data)
    if goplus_section:
        data['goplus'] = goplus_section
    else:
        # Provide minimal valid goplus section when missing
        data['goplus'] = {
            'risk': 'gray',
            'risk_source': 'unavailable'
        }
        degrade = True
        degrade_reasons.append("missing goplus")
    
    # DEX section (required by schema)
    dex_section = _build_dex_section(dex_data)
    if dex_section:
        data['dex'] = dex_section
    else:
        # Provide minimal valid dex section when missing
        data['dex'] = {}
        degrade = True
        degrade_reasons.append("missing dex")
    
    # Check if we have at least one real data source
    if not goplus_data and not dex_data:
        raise ValueError("no usable sources")
    
    # Onchain section (optional)
    onchain_section = _build_onchain_section(onchain_data)
    if onchain_section:
        data['onchain'] = onchain_section
    
    # Rules section (always present)
    if not rules_data:
        degrade = True
        degrade_reasons.append("missing rules")
    
    data['rules'] = _build_rules_section(rules_data, degrade_reasons)
    
    card['data'] = data
    
    # Evidence section (optional)
    evidence_section = _build_evidence_section(evidence_data)
    if evidence_section:
        card['evidence'] = evidence_section
    
    # Calculate data_as_of timestamp
    sources = [goplus_data, dex_data, onchain_data, rules_data]
    data_as_of = _get_oldest_timestamp(sources)
    if not any(sources):
        degrade = True
        degrade_reasons.append("missing data_as_of")
    
    # Set card_type based on available data
    if 'onchain' in data and data.get('rules', {}).get('level') in ['caution', 'risk']:
        card['card_type'] = 'primary'
    elif data.get('rules', {}).get('level') == 'watch':
        card['card_type'] = 'secondary'
    else:
        card['card_type'] = 'topic'
    
    # Generate summary and risk_note
    summary, risk_note, summary_meta = summarize_card(card)
    card['summary'] = summary
    card['risk_note'] = risk_note
    
    # Build meta section
    card['meta'] = {
        'version': 'cards@19.0',
        'data_as_of': data_as_of,
        'summary_backend': summary_meta.get('summary_backend', 'template')
    }
    
    if summary_meta.get('used_refiner'):
        card['meta']['used_refiner'] = summary_meta['used_refiner']
    
    if degrade:
        card['meta']['degrade'] = True
    
    # Optional rendering
    if render:
        rendered_section = _render_card(card)
        if rendered_section:
            card['rendered'] = rendered_section
    
    # Validate against schema
    try:
        schema = _load_schema()
        jsonschema.validate(card, schema)
    except jsonschema.ValidationError as e:
        raise ValueError(f"schema validation failed: {e.message}")
    
    # Log
    try:
        logger = logging.getLogger("cards")
        log_data = {
            "evt": "cards.build",
            "event_key": event_key,
            "has_goplus": 'goplus' in data,
            "has_dex": 'dex' in data,
            "has_onchain": 'onchain' in data,
            "rendered": 'rendered' in card,
            "degrade": degrade,
            "reasons_len": len(degrade_reasons)
        }
        logger.info(json.dumps(log_data, ensure_ascii=False))
    except Exception:
        pass
    
    return card