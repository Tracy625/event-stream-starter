from __future__ import annotations
import os, time, json
from typing import List, Optional, Callable, Sequence, Dict, Any
from pydantic import ValidationError
from openai import OpenAI
from .schemas.refine_schema import RefineModel
from .core.metrics_store import log_json, timeit
from .cache import memoize_ttl

# 兼容不同实现的 memoize_ttl：支持 kw/positional，实在不行就退化为 no-op
def _get_memoize(ttl_seconds: int) -> Callable:
    try:
        # 先试关键字参数版本
        return memoize_ttl(ttl=ttl_seconds)  # type: ignore
    except TypeError:
        try:
            # 再试仅位置参数版本
            return memoize_ttl(ttl_seconds)  # type: ignore
        except TypeError:
            # 最后退化为不缓存
            def _no_cache(f): 
                return f
            return _no_cache

REFINE_BACKEND = os.getenv('REFINE_BACKEND', 'llm')
REFINE_SUMMARY_MAXLEN = int(os.getenv('REFINE_SUMMARY_MAXLEN', '80'))
LATENCY_BUDGET_MS_REFINE = int(os.getenv('LATENCY_BUDGET_MS_REFINE', '800'))
REFINE_TIMEOUT_MS = int(os.getenv('REFINE_TIMEOUT_MS', '1000'))

class RefinerBackend:
    def refine(self, evidence_texts: List[str], *, hint: Optional[str] = None) -> dict:
        raise NotImplementedError

class RulesRefiner(RefinerBackend):
    def refine(self, evidence_texts: List[str], *, hint: Optional[str] = None) -> dict:
        import re
        text = " ".join(evidence_texts)[:1000]
        # 1) 资产抽取：支持对 / 斜杠对，拆成两边；过滤常见噪声
        raw_tokens = re.findall(r"[A-Z]{2,6}(?:/[A-Z]{2,6})?", text)
        tokens: list[str] = []
        for t in raw_tokens:
            if "/" in t:
                a, b = t.split("/", 1)
                tokens += [a, b]
            else:
                tokens.append(t)
        blacklist = {"DEX","RPC","ETF","USD","USDT","USTD","UTC","AM","PM","NFT","DAO","API","NEWS","AIRDROP","MAINNET","TESTNET"}
        assets = []
        for tok in tokens:
            if tok in blacklist: 
                continue
            if tok not in assets:
                assets.append(tok)
        assets = assets[:5]
        # 2) 理由与 summary（先拼再整体截断）
        reasons = []
        low = text.lower()
        if "launch" in low:  reasons.append("New token/project launch")
        if "listing" in low or "list" in low or "pair" in low: reasons.append("Exchange listing or pair opened")
        if not reasons: reasons = ["Heuristic summary"]
        summary_full = f"{hint or 'Update'}: {text}"
        summary = summary_full[:REFINE_SUMMARY_MAXLEN]
        data = {
            "type": "market-update",
            "summary": summary,
            "impacted_assets": assets,
            "reasons": reasons[:4],
            "confidence": 0.35,
        }
        return RefineModel(**data).dict()

class LLMRefiner(RefinerBackend):
    @timeit('refine.llm')
    def refine(self, evidence_texts: List[str], *, hint: Optional[str] = None) -> dict:
        t0 = time.time()
        client = OpenAI()  # 读取 OPENAI_API_KEY
        # 主模型 + 程序级兜底清单（按顺序尝试）
        primary = os.getenv('REFINE_MODEL', 'gpt-4o-mini')
        fallbacks: Sequence[str] = os.getenv('REFINE_FALLBACK_MODELS', 'gpt-4o-mini,gpt-4o').split(',')
        candidates = [m.strip() for m in ([primary] + list(fallbacks)) if m.strip()]
        max_retries = int(os.getenv('REFINE_MAX_RETRIES', '0'))  # 5系/权限错误没必要捶
        timeout_ms = int(os.getenv('REFINE_TIMEOUT_MS', '3000'))
        
        sys = (
            "You are a JSON refiner. "
            f"Return STRICT JSON with keys: type, summary, impacted_assets, reasons, confidence. "
            f"summary <= {REFINE_SUMMARY_MAXLEN} chars; reasons 1-4 items; confidence in [0,1]. "
            "No extra keys, no explanations."
        )
        joined = " ".join(evidence_texts)[:1000]
        
        def _build_kwargs(model: str, messages) -> Dict[str, Any]:
            # gpt-5* 不支持 temperature，别传；其余模型可以传 0.2
            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
                "response_format": {"type": "json_object"},
            }
            if not model.startswith("gpt-5"):
                kwargs["temperature"] = 0.2
            return kwargs
        
        last_exc = None
        # 逐模型尝试；每个模型内做有限重试
        for model in candidates:
            for attempt in range(max_retries + 1):
                try:
                    messages = [
                        {"role": "system", "content": sys},
                        {"role": "user", "content": f"hint={hint or ''}\nEVIDENCE:\n{joined}"},
                    ]
                    resp = client.chat.completions.create(**_build_kwargs(model, messages))
                    raw = resp.choices[0].message.content
                    data = json.loads(raw)
                    if isinstance(data.get("summary"), str):
                        data["summary"] = data["summary"][:REFINE_SUMMARY_MAXLEN].rstrip()
                    out = RefineModel(**data).dict()
                    log_json(stage='refine.success', backend='llm', model=model,
                             latency_ms=int((time.time()-t0)*1000))
                    return out
                except ValidationError as ve:
                    # 模型回了非合规 JSON，没必要换模型，直接降级
                    log_json(stage='refine.reject', reason='schema', error=str(ve)[:200], model=model)
                    log_json(stage='refine.degrade', reason='schema', latency_ms=int((time.time()-t0)*1000))
                    return RulesRefiner().refine(evidence_texts, hint=hint)
                except Exception as e:
                    last_exc = e
                    # gpt-5* 对 temperature 固定：捕捉到这类 400 时，改用不带 temperature 的参数重试一次当前模型
                    msg = str(e)
                    if "Unsupported value: 'temperature'" in msg and model.startswith("gpt-5"):
                        try:
                            resp = client.chat.completions.create(
                                **_build_kwargs(model, messages)  # 这里已无 temperature
                            )
                            raw = resp.choices[0].message.content
                            data = json.loads(raw)
                            if isinstance(data.get("summary"), str):
                                data["summary"] = data["summary"][:REFINE_SUMMARY_MAXLEN].rstrip()
                            out = RefineModel(**data).dict()
                            log_json(stage='refine.success', backend='llm', model=model,
                                     latency_ms=int((time.time()-t0)*1000))
                            return out
                        except Exception as e2:
                            last_exc = e2  # 继续走 fallback
                    # 超预算也打点，避免静默
                    if (time.time()-t0)*1000 > timeout_ms:
                        log_json(stage='refine.degrade', reason='over_budget', latency_ms=int((time.time()-t0)*1000))
                        return RulesRefiner().refine(evidence_texts, hint=hint)
                    if attempt < max_retries:
                        time.sleep(0.05 * (2 ** attempt))
                    else:
                        # 切换到下一个候选模型
                        log_json(stage='refine.error', error=f"{type(e).__name__}: {msg[:200]}", model=model)
                        break
        # 所有候选都失败，最终降级
        log_json(stage='refine.degrade', reason=str(last_exc or 'unknown'),
                 latency_ms=int((time.time()-t0)*1000))
        return RulesRefiner().refine(evidence_texts, hint=hint)

def _backend() -> RefinerBackend:
    if REFINE_BACKEND == 'rules':
        return RulesRefiner()
    return LLMRefiner()

@_get_memoize(30)
def refine_evidence(evidence_texts: List[str], *, hint: Optional[str]=None) -> dict:
    # 打印一次模块路径，防止再跑错文件
    log_json(stage='refine.request', n_inputs=len(evidence_texts), backend=REFINE_BACKEND, module_file=__file__)
    t0 = time.time()
    try:
        out = _backend().refine(evidence_texts, hint=hint)
    except Exception as e:
        # 任何异常都降级到 rules，避免把上游流程炸死
        log_json(stage='refine.degrade', reason='exception', error=str(e))
        out = RulesRefiner().refine(evidence_texts, hint=hint)
        return out
    dt = (time.time()-t0)*1000
    if dt > LATENCY_BUDGET_MS_REFINE and REFINE_BACKEND != 'rules':
        # 只打点，不替换结果；替换只在 LLM 失败/校验失败时发生
        log_json(stage='refine.warn', reason='over_budget', latency_ms=int(dt))
    return out