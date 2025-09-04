"""Contract address normalization utility"""
from typing import Optional
import re
from api.metrics import log_json


def normalize_ca(chain: str, ca: Optional[str], is_official_guess: bool = False) -> dict:
    """
    Normalize contract address for a given chain
    
    Args:
        chain: Blockchain identifier (eth/bsc/arb/op/base for EVM, sol for non-EVM)
        ca: Raw contract address string
        is_official_guess: Whether this is an official guess
    
    Returns:
        Dictionary with normalization result:
        {
            "ca_norm": Normalized address or None,
            "valid": Whether address is valid,
            "is_official_guess": Pass-through of input flag
        }
    """
    # Initialize result
    result = {
        "ca_norm": None,
        "valid": False,
        "is_official_guess": is_official_guess
    }
    
    # Handle None/empty input
    if not ca or not isinstance(ca, str):
        log_json(
            stage="ca.normalize",
            chain=chain,
            raw=ca,
            norm=None,
            valid=False,
            is_official_guess=is_official_guess
        )
        return result
    
    # Clean whitespace
    raw = ca.strip() if isinstance(ca, str) else ca
    
    # Handle EVM chains
    if chain in {"eth", "bsc", "arb", "op", "base"}:
        # EVM: 允许无 0x，统一小写并补前缀；仅接受 40 个十六进制字符
        s = raw.lower() if raw else ""
        # 去掉 0x 前缀（如果有）
        s_wo0x = s[2:] if s.startswith("0x") else s
        # 防御性处理：去除非十六进制字符（避免隐性空白或奇怪的分隔符）
        s_wo0x = "".join(ch for ch in s_wo0x if ch in "0123456789abcdef")
        if len(s_wo0x) == 40 and re.fullmatch(r"[0-9a-f]{40}", s_wo0x):
            result["ca_norm"] = "0x" + s_wo0x
            result["valid"] = True
        else:
            result["ca_norm"] = None
            result["valid"] = False
        
        log_json(
            stage="ca.normalize",
            chain=chain,
            raw=ca,
            norm=result["ca_norm"],
            valid=result["valid"],
            is_official_guess=is_official_guess
        )
        return result
    
    # Handle non-EVM chains (sol, etc.) - no normalization
    # Return None for ca_norm, valid=False
    log_json(
        stage="ca.normalize",
        chain=chain,
        raw=ca,
        norm=None,
        valid=False,
        is_official_guess=is_official_guess
    )
    return result