import logging
import os
import re
from typing import List, Tuple

try:
    import torch
    from transformers import AutoModel, AutoTokenizer
except Exception:
    torch = None
    AutoTokenizer = AutoModel = None
LOGGER = logging.getLogger(__name__)
DEFAULT_TOPK = int(os.getenv("KEYPHRASE_TOPK", "5"))
DEFAULT_MIN_LEN = int(os.getenv("KEYPHRASE_MIN_LEN", "2"))
DEFAULT_DEDUP = os.getenv("KEYPHRASE_DEDUP", "1") == "1"
FALLBACK_ON_EMPTY = os.getenv("KEYPHRASE_FALLBACK_ON_EMPTY", "1") == "1"
KBIR_MODEL = os.getenv("KEYPHRASE_MODEL", "ml6team/keyphrase-extraction-kbir-inspec")
ALPHA = float(os.getenv("KEYPHRASE_MMR_ALPHA", "0.65"))
MAX_NGRAM = int(os.getenv("KEYPHRASE_MAX_N", "3"))
DEVICE = "cuda" if (os.getenv("HF_DEVICE", "cpu") == "cuda") else "cpu"

STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "for",
    "to",
    "of",
    "on",
    "in",
    "with",
    "at",
    "by",
    "is",
    "are",
    "was",
    "were",
    "this",
    "that",
    "it",
    "its",
    "as",
    "be",
    "from",
    "now",
    "open",
    "new",
    "claim",
    "get",
    "go",
    "you",
    "we",
}


def extract_keyphrases(text: str) -> List[str]:
    backend = os.getenv("KEYPHRASE_BACKEND", "off")
    if backend == "off":
        return _rules_extract(text)

    if backend == "kbir":

        topk = 8 if len(text) < 64 else (DEFAULT_TOPK or 5)
        phrases = _kbir_extract(text, topk=topk)
        phrases = _normalize_filter(
            phrases, min_len=DEFAULT_MIN_LEN, dedup=DEFAULT_DEDUP
        )
        if not phrases and FALLBACK_ON_EMPTY:
            LOGGER.info(
                "keyphrases.downgrade",
                extra={"backend": "kbir", "reason": "empty_result", "downgrade": True},
            )
            return _rules_extract(text)
        return phrases
    return _rules_extract(text)


def _rules_extract(text: str) -> List[str]:
    toks = re.findall(r"\$[A-Za-z0-9_]+|[A-Za-z]{2,}", text)
    base = [t.lower() for t in toks]
    base = [t for t in base if t not in STOPWORDS]
    seen, out = set(), []
    for s in base:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[: DEFAULT_TOPK or 5]


_KBIR_CACHE = {"tok": None, "model": None, "device": "cpu"}


def _load_kbir():
    if torch is None or AutoTokenizer is None or AutoModel is None:
        raise RuntimeError("transformers/torch not available for KBIR backend")
    if _KBIR_CACHE["tok"] is None:
        dev = "cuda" if (DEVICE == "cuda" and torch.cuda.is_available()) else "cpu"
        LOGGER.info("[KBIR] loading model %s on %s", KBIR_MODEL, dev)
        tok = AutoTokenizer.from_pretrained(KBIR_MODEL)
        mdl = AutoModel.from_pretrained(KBIR_MODEL)
        mdl.eval()
        for p in mdl.parameters():
            p.requires_grad = False
        mdl.to(dev)
        _KBIR_CACHE.update({"tok": tok, "model": mdl, "device": dev})
    return _KBIR_CACHE["tok"], _KBIR_CACHE["model"], _KBIR_CACHE["device"]


def _mean_pool(
    last_hidden_state: "torch.Tensor", attention_mask: "torch.Tensor"
) -> "torch.Tensor":
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    masked = last_hidden_state * mask
    summed = masked.sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


def _gen_ngrams(tokens: List[str], max_n: int) -> List[Tuple[str, Tuple[int, int]]]:
    spans = []
    n = len(tokens)
    for i in range(n):
        for k in range(1, max_n + 1):
            j = i + k
            if j > n:
                break
            phrase = " ".join(tokens[i:j])
            spans.append((phrase, (i, j)))
    return spans


def _kbir_extract(text: str, topk: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    tok, mdl, dev = _load_kbir()
    raw_tokens = re.findall(r"\$[A-Za-z0-9_]+|[A-Za-z]+|\d+", text)
    tokens = [t for t in raw_tokens if t.strip()]
    cand_spans = _gen_ngrams(tokens, max_n=MAX_NGRAM)
    if not cand_spans:
        cand_spans = [(t, (i, i + 1)) for i, t in enumerate(tokens)]
    phrases = [p for p, _ in cand_spans]

    with torch.no_grad():
        enc = tok(text, return_tensors="pt", truncation=True, max_length=256).to(dev)
        out = mdl(**enc)
        doc_vec = _mean_pool(out.last_hidden_state, enc["attention_mask"])
        doc_vec = torch.nn.functional.normalize(doc_vec, dim=-1)

        p_vecs = []
        for phrase in phrases:
            pe = tok(phrase, return_tensors="pt", truncation=True, max_length=16).to(
                dev
            )
            po = mdl(**pe)
            vec = _mean_pool(po.last_hidden_state, pe["attention_mask"])
            vec = torch.nn.functional.normalize(vec, dim=-1)
            p_vecs.append(vec)

    sims = [float(torch.mm(v, doc_vec.T).squeeze().item()) for v in p_vecs]
    idx_sorted = sorted(range(len(phrases)), key=lambda i: sims[i], reverse=True)[
        : max(50, topk)
    ]

    if not idx_sorted:
        return []

    selected = [idx_sorted[0]]
    candidates = idx_sorted[1:]
    while len(selected) < topk and candidates:
        best_i, best_score = None, -1e9
        for i in candidates:
            rel = sims[i]
            div = 0.0
            for j in selected:
                div += float(torch.mm(p_vecs[i], p_vecs[j].T).squeeze().item())
            div = div / max(1, len(selected))
            score = ALPHA * rel - (1 - ALPHA) * div
            if score > best_score:
                best_score, best_i = score, i
        selected.append(best_i)
        candidates.remove(best_i)

    return [phrases[i] for i in selected]


def _normalize_filter(
    cands: List[str], min_len: int = 2, dedup: bool = True
) -> List[str]:
    out, seen = [], set()
    for c in cands:
        s = c.strip().lower()
        if len(s) < min_len:
            continue
        if s in STOPWORDS:
            continue
        if dedup and s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[: DEFAULT_TOPK or 5]
