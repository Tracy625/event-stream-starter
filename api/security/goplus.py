"""GoPlus security evaluation for Primary card enforcement"""

import os
from typing import Any, Dict, Optional

from api.config.hotreload import get_registry
from api.core.metrics_store import log_json


def load_risk_rules() -> Dict[str, Any]:
    """Load risk rules from registry with hot reload support"""
    try:
        registry = get_registry()
        # Check for stale configs and reload if needed
        registry.reload_if_stale()
        # Get risk_rules namespace
        return registry.get_ns("risk_rules")
    except Exception as e:
        log_json(stage="goplus.rules.load_error", error=str(e))
        return {}


def evaluate_goplus_raw(goplus_raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluate raw GoPlus data to determine risk assessment

    Args:
        goplus_raw: Raw response from GoPlus API or None if unavailable

    Returns:
        Dictionary with risk assessment for Primary card gate:
        {
            "status": "ok|timeout|error|missing",
            "version": "GoPlus@vX.Y|GoPlus@unknown",
            "findings": {"risk_color": "red|yellow|green|gray"},
            "forbid_green": true/false,
            "risk_note": "...",
            "risk_source": "GoPlus@...",
            "rules_fired": []
        }
    """
    rules = load_risk_rules()

    # Get version from rules or environment (at call-time)
    goplus_version = rules.get("goplus_version") or os.getenv(
        "GOPLUS_VERSION", "GoPlus@v1.2"
    )
    if not goplus_version.startswith("GoPlus@"):
        goplus_version = "GoPlus@" + goplus_version

    # If no GoPlus data, return missing/degraded state
    if not goplus_raw:
        log_json(stage="goplus.missing", action="force_gray")
        return {
            "status": "missing",
            "version": "GoPlus@unknown",
            "findings": {"risk_color": "gray"},
            "forbid_green": True,
            "risk_note": "安全检查未执行",
            "risk_source": "GoPlus@unknown",
            "rules_fired": ["goplus_missing"],
        }

    # Check if this is an error/timeout response
    if goplus_raw.get("error") or goplus_raw.get("degrade"):
        status = (
            "timeout"
            if "timeout" in str(goplus_raw.get("error", "")).lower()
            else "error"
        )
        degradation = rules.get("degradation", {})
        config = degradation.get(
            "on_timeout" if status == "timeout" else "on_error", {}
        )

        log_json(stage="goplus.degraded", status=status)
        return {
            "status": status,
            "version": "GoPlus@unknown",
            "findings": {"risk_color": config.get("risk_color", "gray")},
            "forbid_green": config.get("forbid_green", True),
            "risk_note": config.get("risk_note", "体检服务异常，已降级"),
            "risk_source": "GoPlus@unknown",
            "rules_fired": ["degraded_mode"],
        }

    # Extract data from GoPlus response
    # Handle both direct response and wrapped result
    result_data = goplus_raw.get("result", goplus_raw)
    if isinstance(result_data, dict) and len(result_data) == 1:
        # If result is a dict with single token address key, extract it
        result_data = list(result_data.values())[0] if result_data else {}

    # Parse risk indicators
    honeypot = str(result_data.get("is_honeypot", "0")) == "1"
    buy_tax = _parse_tax(result_data.get("buy_tax"))
    sell_tax = _parse_tax(result_data.get("sell_tax"))
    lp_lock_days = _parse_lp_lock(result_data)

    # Get thresholds from rules
    thresholds = rules.get("risk_thresholds", {})
    honeypot_red = thresholds.get("honeypot_red", True)
    buy_tax_red = thresholds.get("buy_tax_red", 10)
    sell_tax_red = thresholds.get("sell_tax_red", 10)
    lp_lock_yellow = thresholds.get("lp_lock_yellow_days", 30)

    # Determine risk color and collect rules fired
    rules_fired = []
    risk_color = "green"  # Default to green if no issues found
    risk_note = ""

    # Check red conditions
    if honeypot and honeypot_red:
        risk_color = "red"
        risk_note = "蜜罐合约"
        rules_fired.append("honeypot_detected")
    elif buy_tax and buy_tax > buy_tax_red:
        risk_color = "red"
        risk_note = f"买入税{buy_tax:.1f}%"
        rules_fired.append("high_buy_tax")
    elif sell_tax and sell_tax > sell_tax_red:
        risk_color = "red"
        risk_note = f"卖出税{sell_tax:.1f}%"
        rules_fired.append("high_sell_tax")
    # Check yellow conditions
    elif lp_lock_days is not None and lp_lock_days < lp_lock_yellow:
        risk_color = "yellow"
        risk_note = f"LP锁仓不足: {lp_lock_days}天"
        rules_fired.append("low_lp_lock")
    # If no red/yellow conditions triggered but we have data, it stays green
    # risk_color already defaulted to green above

    log_json(stage="goplus.evaluated", risk_color=risk_color, rules_fired=rules_fired)

    return {
        "status": "ok",
        "version": goplus_version,
        "findings": {"risk_color": risk_color},
        "forbid_green": False,
        "risk_note": risk_note,
        "risk_source": goplus_version,
        "rules_fired": rules_fired,
    }


def _parse_tax(tax_value) -> Optional[float]:
    """Parse tax value from various formats"""
    if tax_value is None:
        return None
    try:
        val = float(tax_value)
        # If <= 1, assume it's a ratio and convert to percentage
        return val * 100 if val <= 1.0 else val
    except:
        return None


def _parse_lp_lock(data: Dict[str, Any]) -> Optional[int]:
    """Parse LP lock days from response"""
    # This is a placeholder - actual field name may vary
    # Return 0 if LP holders exist but no lock info
    if data.get("lp_holders"):
        return 0
    return None
