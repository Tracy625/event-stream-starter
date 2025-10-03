"""
Day19 Card Summarizer - Constrained text generation for summary and risk_note
"""

import importlib
import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, Optional, Tuple


def _env_int(name: str, default: int) -> int:
    """Read integer from environment variable"""
    try:
        return int(os.environ.get(name, str(default)))
    except (ValueError, TypeError):
        return default


def _env_str(name: str, default: str) -> str:
    """Read string from environment variable"""
    return os.environ.get(name, default)


def _extract_symbol(payload: dict) -> str:
    """Extract symbol from payload or event_key"""
    if symbol := payload.get("symbol"):
        return str(symbol)

    event_key = payload.get("event_key", "")
    if ":" in event_key:
        parts = event_key.split(":")
        if parts[0] and parts[0].upper() in ["ETH", "SOL", "BSC", "MATIC", "ARB"]:
            return parts[0].upper()

    return "Token"


def _extract_price(payload: dict) -> Optional[float]:
    """Extract price from data.dex.price_usd"""
    try:
        if data := payload.get("data"):
            if dex := data.get("dex"):
                if price := dex.get("price_usd"):
                    return float(price)
    except (TypeError, ValueError):
        pass
    return None


def _extract_liq(payload: dict) -> Optional[float]:
    """Extract liquidity from data.dex.liquidity_usd"""
    try:
        if data := payload.get("data"):
            if dex := data.get("dex"):
                if liq := dex.get("liquidity_usd"):
                    return float(liq)
    except (TypeError, ValueError):
        pass
    return None


def _extract_level(payload: dict) -> str:
    """Extract rules level"""
    try:
        if data := payload.get("data"):
            if rules := data.get("rules"):
                if level := rules.get("level"):
                    return str(level)
    except (TypeError, KeyError):
        pass
    return "unknown"


def _extract_risk(payload: dict) -> str:
    """Extract goplus risk"""
    try:
        if data := payload.get("data"):
            if goplus := data.get("goplus"):
                if risk := goplus.get("risk"):
                    return str(risk)
    except (TypeError, KeyError):
        pass
    return "unknown"


def _format_number(num: Optional[float]) -> str:
    """Format number using .6g format"""
    if num is None:
        return ""
    return f"{num:.6g}"


def _strip_trailing_punct(s: str) -> str:
    """Remove trailing punctuation and spaces"""
    return s.rstrip(" ,;，；")


def _squeeze_spaces(s: str) -> str:
    """Replace multiple spaces with single space"""
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _truncate(s: str, max_chars: int) -> str:
    """Truncate string to max_chars with ellipsis if needed"""
    s = _squeeze_spaces(s)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _render_template(
    symbol: str, price: Optional[float], liq: Optional[float], level: str, risk: str
) -> Tuple[str, str]:
    """Render template-based summary and risk_note"""

    # Build summary
    parts = [symbol]

    if price is not None:
        parts.append(f"价格≈${_format_number(price)}")

    if liq is not None:
        parts.append(f"流动性≈${_format_number(liq)}")

    parts.append(f"规则判定{level}")

    summary = " | ".join(parts)
    summary = _strip_trailing_punct(summary)

    # Build risk_note
    risk_note = f"合约体检{risk}；关注税率/LP/交易限制"

    return summary, risk_note


def _resolve_refiner() -> tuple[Optional[Any], str]:
    """
    Dynamically import a refiner class by env path.
    Env: CARDS_REFINER_CLASS_PATH like 'api.refine:MiniRefiner'
         or 'api.hf_adapter:HFRefiner'
    Returns (instance or None, refiner_name)
    """
    class_path = os.environ.get("CARDS_REFINER_CLASS_PATH", "").strip()
    if not class_path:
        # Try a few common defaults without exploding
        candidates = [
            "api.refine:MiniRefiner",
            "api.hf_adapter:HFRefiner",
            "api.refiner:RefinerClient",
        ]
    else:
        candidates = [class_path]

    for path in candidates:
        try:
            mod_name, cls_name = path.split(":")
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            return cls(), cls_name
        except Exception:
            continue
    return None, ""


def _call_refiner(
    payload: dict, timeout_ms: int, max_sum: int, max_note: int
) -> Optional[Tuple[str, str, str]]:
    """
    Call Day6 mini-LLM refiner for summarization.
    Returns (summary, risk_note, refiner_name) or None on any failure.
    """
    inst, refiner_name = _resolve_refiner()
    if inst is None:
        return None

    # Build a compact, language-pinned instruction with hard length caps
    ctx = {
        "price_usd": _extract_price(payload),
        "liquidity_usd": _extract_liq(payload),
        "level": _extract_level(payload),
        "risk": _extract_risk(payload),
    }

    system = (
        f"你是严格的文本压缩器。仅输出 JSON："
        f'{{"summary":"...", "risk_note":"..."}}。'
        f"中文输出；不得包含投资建议、emoji、夸张修辞；summary≤{max_sum}字，risk_note≤{max_note}字。"
        f"缺字段则省略相应表述，不得编造。单行文本。"
    )
    prompt = {"system": system, "context": ctx}

    try:
        # Try common method names; refiner should accept json-like input and timeout
        for meth in ("refine", "summarize", "run"):
            if hasattr(inst, meth):
                fn: Callable[..., Any] = getattr(inst, meth)
                res = fn(prompt, timeout_ms=timeout_ms)
                break
        else:
            return None

        # Expect JSON-like result
        if isinstance(res, str):
            try:
                res = json.loads(res)
            except Exception:
                return None

        summary = str(res.get("summary", "") or "").strip()
        risk_note = str(res.get("risk_note", "") or "").strip()

        if not summary or not risk_note:
            return None

        return summary, risk_note, refiner_name
    except Exception:
        return None


def summarize_card(
    input_payload: dict, timeout_ms: Optional[int] = None
) -> Tuple[str, str, dict]:
    """
    Generate summary and risk_note for a card

    Returns:
        summary: str (non-empty, <= max chars)
        risk_note: str (non-empty, <= max chars)
        meta_extra: dict with at least:
            - summary_backend: "llm" | "template"
            - used_refiner: str | ""
    """
    start_time = time.time()

    # Read environment variables
    backend = _env_str("CARDS_SUMMARY_BACKEND", "llm")
    default_timeout = _env_int("CARDS_SUMMARY_TIMEOUT_MS", 1200)
    max_summary_chars = _env_int("CARDS_SUMMARY_MAX_CHARS", 280)
    max_risknote_chars = _env_int("CARDS_RISKNOTE_MAX_CHARS", 160)

    if timeout_ms is None:
        timeout_ms = default_timeout

    # Extract fields
    symbol = _extract_symbol(input_payload)
    price = _extract_price(input_payload)
    liq = _extract_liq(input_payload)
    level = _extract_level(input_payload)
    risk = _extract_risk(input_payload)

    # Track what we found for logging
    had_price = price is not None
    had_liq = liq is not None
    had_rules = level != "unknown"
    had_risk = risk != "unknown"

    # Check if we have minimal data
    if not (had_price or had_rules):
        # Insufficient data, use template
        backend = "template"

    # Try LLM if configured
    used_refiner = ""
    degrade = False
    if backend == "llm" and timeout_ms > 1:
        llm_result = _call_refiner(
            input_payload, timeout_ms, max_summary_chars, max_risknote_chars
        )
        if llm_result:
            summary, risk_note, used_refiner = llm_result
            actual_backend = "llm"
        else:
            # LLM failed, fallback to template
            degrade = True
            summary, risk_note = _render_template(symbol, price, liq, level, risk)
            actual_backend = "template"
    else:
        # Direct template mode
        summary, risk_note = _render_template(symbol, price, liq, level, risk)
        actual_backend = "template"

    # Clean and truncate
    summary = _truncate(summary, max_summary_chars)
    risk_note = _truncate(risk_note, max_risknote_chars)

    # Ensure non-empty
    if not summary:
        summary = f"{symbol} 信息不足"
    if not risk_note:
        risk_note = "风险信息待补充"

    # Calculate elapsed time
    elapsed_ms = int((time.time() - start_time) * 1000)

    # Log
    log_data = {
        "backend": actual_backend,
        "timeout_ms": timeout_ms,
        "elapsed_ms": elapsed_ms,
        "degrade": degrade,
        "had_price": had_price,
        "had_liq": had_liq,
        "had_rules": had_rules,
        "had_risk": had_risk,
        "max_summary": max_summary_chars,
        "max_note": max_risknote_chars,
    }

    try:
        logger = logging.getLogger("cards")
        logger.info(
            json.dumps({"evt": "cards.summarize", **log_data}, ensure_ascii=False)
        )
    except Exception:
        pass

    meta_extra = {"summary_backend": actual_backend, "used_refiner": used_refiner}

    return summary, risk_note, meta_extra
