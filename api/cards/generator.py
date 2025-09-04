"""Card generator with template rendering and schema validation"""
import json
import os
from typing import Dict, Any
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader
from jsonschema import validate, ValidationError, Draft7Validator
from api.utils.ca import normalize_ca
from api.cards.dedup import make_state_version, should_emit, mark_emitted

def log_json(stage: str, **kwargs):
    """Structured JSON logging"""
    log_entry = {"stage": stage, **kwargs}
    print(f"[JSON] {json.dumps(log_entry)}")

def generate_card(event: Dict[str, Any], signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate card from event and signals data
    
    Args:
        event: Event data with type, risk_level, token_info, etc.
        signals: Signal data with dex_snapshot and goplus_raw
        
    Returns:
        Card dict conforming to pushcard.schema.json with optional rendered fields
    """
    try:
        # Enforce Primary card gate if needed
        if event.get("type") == "primary":
            # Evaluate GoPlus raw data locally
            from api.security.goplus import evaluate_goplus_raw
            goplus_raw = signals.get("goplus_raw")
            assessment = evaluate_goplus_raw(goplus_raw)
            
            # Apply assessment to event
            risk_color = assessment["findings"]["risk_color"]
            
            # Forbid green if degraded
            if assessment.get("forbid_green") and risk_color == "green":
                risk_color = "gray"
                assessment["risk_note"] = "安全检查不完整"
                log_json(
                    stage="primary_gate.forbid_green",
                    original="green",
                    forced="gray"
                )
            
            # Update event with gate results
            event["risk_level"] = risk_color
            event["risk_note"] = assessment.get("risk_note", "")
            event["risk_source"] = assessment["risk_source"]
            event["rules_fired"] = assessment["rules_fired"]
            # Mark as degraded if gray
            if risk_color == "gray":
                event["is_degraded"] = True
            
            log_json(
                stage="primary_gate.applied",
                risk_level=event["risk_level"],
                risk_source=event["risk_source"],
                rules_fired=event["rules_fired"]
            )
        
        # State-based deduplication check (after Primary gate)
        event_key = event.get("event_key")
        state_version = None  # Initialize for later reference
        if event_key:
            # Prepare states for dedup
            if "states" not in event:
                event["states"] = {}
            # Sync degrade flag from is_degraded or risk_level
            if "degrade" not in event["states"]:
                event["states"]["degrade"] = event.get("is_degraded", False) or event.get("risk_level") == "gray"
            
            state_version = make_state_version(event)
            can_emit, reason = should_emit(event_key, state_version)
            
            if not can_emit:
                log_json(
                    stage="dedup.skip",
                    event_key=event_key,
                    state_version=state_version,
                    reason=reason
                )
                return {
                    "skipped": True,
                    "event_key": event_key,
                    "state_version": state_version,
                    "reason": reason
                }
        
        # Extract DEX data
        dex_data = signals.get("dex_snapshot", {})
        goplus_data = signals.get("goplus_raw", {})
        
        # Build card structure with CA normalization
        token_info = event.get("token_info", {}).copy()  # Copy to avoid modifying original
        
        # Normalize CA if present
        if "ca" in token_info:
            chain = token_info.get("chain", "eth")
            ca_result = normalize_ca(chain, token_info["ca"], is_official_guess=False)
            if ca_result["valid"]:
                token_info["ca_norm"] = ca_result["ca_norm"]
            # Remove raw ca field (not in schema)
            del token_info["ca"]
        # Fallback for legacy ca_norm field
        elif "ca_norm" in token_info:
            # Validate existing ca_norm
            chain = token_info.get("chain", "eth")
            ca_result = normalize_ca(chain, token_info["ca_norm"], is_official_guess=False)
            if ca_result["valid"]:
                token_info["ca_norm"] = ca_result["ca_norm"]
            else:
                # Remove invalid ca_norm
                del token_info["ca_norm"]
        
        # Ensure ca_norm exists for template rendering (display fallback)
        if "ca_norm" not in token_info:
            # Use a placeholder for display purposes
            token_info["ca_norm"] = "0x" + "0" * 40  # Display placeholder
        
        card = {
            "type": event.get("type", "primary"),
            "risk_level": event.get("risk_level", "yellow"),
            "token_info": token_info,
            "metrics": {
                "price_usd": dex_data.get("price_usd"),
                "liquidity_usd": dex_data.get("liquidity_usd"),
                "fdv": dex_data.get("fdv"),
                "ohlc": dex_data.get("ohlc", {
                    "m5": {"o": None, "h": None, "l": None, "c": None},
                    "h1": {"o": None, "h": None, "l": None, "c": None},
                    "h24": {"o": None, "h": None, "l": None, "c": None}
                })
            },
            "sources": {
                "security_source": event.get("risk_source", "GoPlus@unknown" if event.get("type") == "primary" else ""),
                "dex_source": dex_data.get("source", "")
            },
            "states": {
                "cache": dex_data.get("cache", False),
                "degrade": event.get("is_degraded", dex_data.get("degrade", False)),
                "stale": dex_data.get("stale", False),
                "reason": dex_data.get("reason", "")
            },
            "evidence": {
                "goplus_raw": {
                    "summary": goplus_data.get("summary", "")
                } if goplus_data else {}
            },
            "risk_note": event.get("risk_note", ""),
            "verify_path": event.get("verify_path", "/"),
            "data_as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")  # Minute precision
        }
        
        # Secondary card enhancements
        if event.get("type") == "secondary":
            # Determine source_level from signals/source
            signal_source = signals.get("source", "").lower()
            # Only mark as confirmed if explicitly verified/confirmed
            if ("verified" in signal_source and "unverified" not in signal_source) or "confirmed" in signal_source:
                source_level = "confirmed"
            else:
                source_level = "rumor"
            
            # Add features_snapshot (placeholder until Day12)
            features_snapshot = {
                "active_addrs": None,
                "top10_share": None,
                "growth_30m": None,
                "stale": True
            }
            
            # Add secondary-specific fields
            card["source_level"] = source_level
            card["features_snapshot"] = features_snapshot
            
            # If features are stale, add risk_note if not already present
            if features_snapshot["stale"] and not card["risk_note"]:
                card["risk_note"] = "二级卡数据暂不可用"
            
            # Log secondary card emission
            log_json(
                stage="secondary_emit",
                source_level=source_level,
                has_features_snapshot=True,
                stale=features_snapshot["stale"]
            )
        
        # Add optional fields if present
        if "rules_fired" in event:
            card["rules_fired"] = event["rules_fired"]
        if "legal_note" in event:
            card["legal_note"] = event["legal_note"]
        # Note: risk_source is already in sources.security_source
            
        # Validate against schema BEFORE adding rendered field
        schema_path = "schemas/pushcard.schema.json"
        if os.path.exists(schema_path):
            with open(schema_path, 'r') as f:
                schema = json.load(f)
            Draft7Validator.check_schema(schema)
            validate(card, schema)
        
        # Render templates (after validation)
        try:
            template_dir = "templates/cards"
            
            # Select template based on card type
            template_base = "secondary_card" if card["type"] == "secondary" else "primary_card"
            
            # Telegram template (no autoescape)
            tg_env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=False
            )
            tg_template = tg_env.get_template(f"{template_base}.tg.j2")
            tg_rendered = tg_template.render(card_data=card)
            
            # UI template (with autoescape)
            ui_env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=True
            )
            ui_template = ui_env.get_template(f"{template_base}.ui.j2")
            ui_rendered = ui_template.render(card_data=card)
            
            # Add rendered content AFTER validation
            card["rendered"] = {
                "tg": tg_rendered,
                "ui": ui_rendered
            }
        except Exception as e:
            log_json(
                stage="card.template.error",
                error=str(e)
            )
            raise
        
        # Log successful generation
        log_json(
            stage="card.generate",
            risk_level=card["risk_level"],
            cache=card["states"]["cache"],
            stale=card["states"]["stale"],
            degrade=card["states"]["degrade"],
            reason=card["states"]["reason"],
            source=card["sources"]["dex_source"]
        )
        
        # Mark as emitted for deduplication
        if event_key and state_version:
            mark_emitted(event_key, state_version)
        
        return card
        
    except ValidationError as e:
        log_json(
            stage="card.schema.error",
            error=str(e)
        )
        raise
    except Exception as e:
        log_json(
            stage="card.generate.error",
            error=str(e)
        )
        raise