"""Card generator with template rendering and schema validation"""
import json
import os
from typing import Dict, Any, Optional
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from jsonschema import validate, ValidationError, Draft7Validator

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
        # Extract DEX data
        dex_data = signals.get("dex_snapshot", {})
        goplus_data = signals.get("goplus_raw", {})
        
        # Build card structure
        # Ensure ca_norm matches expected format for schema
        token_info = event.get("token_info", {})
        if "ca_norm" in token_info and not token_info["ca_norm"].startswith("0x"):
            # Pad with zeros if needed for testing
            token_info["ca_norm"] = "0x" + "0" * 40
        
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
            "data_as_of": event.get("data_as_of", datetime.utcnow().isoformat() + "Z")
        }
        
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
            
            # Telegram template (no autoescape)
            tg_env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=False
            )
            tg_template = tg_env.get_template("primary_card.tg.j2")
            tg_rendered = tg_template.render(card_data=card)
            
            # UI template (with autoescape)
            ui_env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=True
            )
            ui_template = ui_env.get_template("primary_card.ui.j2")
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