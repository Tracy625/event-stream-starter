"""
KBIR-based keyphrase extraction with MMR (Maximal Marginal Relevance).

Advanced implementation using document embeddings and diversity-aware selection.
"""

import logging
import math
import os
import re
from collections import Counter
from typing import List, Tuple

import torch
from transformers import AutoModel, AutoTokenizer

LOGGER = logging.getLogger(__name__)

# Configuration
DEFAULT_TOPK = int(os.getenv("KEYPHRASE_TOPK", "5"))
DEFAULT_MIN_LEN = int(os.getenv("KEYPHRASE_MIN_LEN", "2"))
DEFAULT_DEDUP = os.getenv("KEYPHRASE_DEDUP", "1") == "1"
FALLBACK_ON_EMPTY = os.getenv("KEYPHRASE_FALLBACK_ON_EMPTY", "1") == "1"
KBIR_MODEL = os.getenv("KEYPHRASE_MODEL", "ml6team/keyphrase-extraction-kbir-inspec")
ALPHA = float(os.getenv("KEYPHRASE_MMR_ALPHA", "0.65"))  # relevance weight for MMR
MAX_NGRAM = int(os.getenv("KEYPHRASE_MAX_N", "3"))  # 1-3 word phrases
DEVICE = (
    "cuda"
    if (os.getenv("HF_DEVICE", "cpu") == "cuda" and torch.cuda.is_available())
    else "cpu"
)

# Common stopwords
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "that",
    "the",
    "to",
    "was",
    "will",
    "with",
    "this",
    "but",
    "they",
    "have",
    "had",
    "what",
    "when",
    "where",
    "who",
    "which",
    "why",
    "how",
}

# Global cache for KBIR model
_KBIR_CACHE = {"tok": None, "model": None}


def _load_kbir():
    """Load and cache KBIR model."""
    if _KBIR_CACHE["tok"] is None:
        LOGGER.info(f"[KBIR] Loading model {KBIR_MODEL} on {DEVICE}")
        tok = AutoTokenizer.from_pretrained(KBIR_MODEL)
        mdl = AutoModel.from_pretrained(KBIR_MODEL)
        mdl.eval()
        for p in mdl.parameters():
            p.requires_grad = False
        mdl.to(DEVICE)
        _KBIR_CACHE["tok"] = tok
        _KBIR_CACHE["model"] = mdl
    return _KBIR_CACHE["tok"], _KBIR_CACHE["model"]


def _mean_pool(
    last_hidden_state: torch.Tensor, attention_mask: torch.Tensor
) -> torch.Tensor:
    """Mean pooling over token embeddings."""
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    masked = last_hidden_state * mask
    summed = masked.sum(dim=1)
    counts = mask.sum(dim=1).clamp(min=1e-9)
    return summed / counts


def _gen_ngrams(tokens: List[str], max_n: int = 3) -> List[Tuple[str, Tuple[int, int]]]:
    """Generate n-grams from tokens."""
    spans = []
    n = len(tokens)
    for i in range(n):
        for k in range(1, min(max_n + 1, n - i + 1)):
            j = i + k
            phrase = " ".join(tokens[i:j])
            spans.append((phrase, (i, j)))
    return spans


def _kbir_extract(text: str, topk: int) -> List[str]:
    """
    KBIR keyphrase extraction using MMR.

    1. Generate candidate phrases (n-grams)
    2. Compute embeddings for document and candidates
    3. Use MMR to select diverse, relevant keyphrases
    """
    if not text or text.strip() == "":
        return []

    tok, mdl = _load_kbir()

    # Tokenize preserving $SYMBOL tokens
    raw_tokens = re.findall(r"\$[A-Za-z0-9_]+|[A-Za-z]+|\d+", text)
    tokens = [t for t in raw_tokens if t.strip()]

    # Generate candidate phrases
    cand_spans = _gen_ngrams(tokens, max_n=MAX_NGRAM)
    if not cand_spans:
        cand_spans = [(t, (i, i + 1)) for i, t in enumerate(tokens)]

    # Compute document embedding
    with torch.no_grad():
        enc = tok(text, return_tensors="pt", truncation=True, max_length=256).to(DEVICE)
        out = mdl(**enc)
        doc_vec = _mean_pool(out.last_hidden_state, enc["attention_mask"])
        doc_vec = torch.nn.functional.normalize(doc_vec, dim=-1)

    # Compute candidate embeddings
    phrase_vecs = []
    phrases = []
    with torch.no_grad():
        for phrase, _span in cand_spans:
            pe = tok(phrase, return_tensors="pt", truncation=True, max_length=16).to(
                DEVICE
            )
            po = mdl(**pe)
            vec = _mean_pool(po.last_hidden_state, pe["attention_mask"])
            vec = torch.nn.functional.normalize(vec, dim=-1)
            phrase_vecs.append(vec)
            phrases.append(phrase)

    # Calculate relevance scores (similarity to document)
    sims = [float(torch.mm(pv, doc_vec.T).squeeze().item()) for pv in phrase_vecs]

    # Pre-filter: take top 50 candidates by relevance
    idx_sorted = sorted(range(len(phrases)), key=lambda i: sims[i], reverse=True)[
        : max(50, topk)
    ]

    if not idx_sorted:
        return []

    # MMR selection
    selected_idx = []
    candidate_idx = idx_sorted.copy()

    # Initialize with most relevant phrase
    selected_idx.append(candidate_idx.pop(0))

    # Iteratively select phrases that balance relevance and diversity
    while len(selected_idx) < topk and candidate_idx:
        best_i, best_score = None, -1e9

        for i in candidate_idx:
            # Relevance score
            rel = sims[i]

            # Diversity penalty (average similarity to already selected)
            div = 0.0
            for j in selected_idx:
                div += float(
                    torch.mm(phrase_vecs[i], phrase_vecs[j].T).squeeze().item()
                )
            div = div / max(1, len(selected_idx))

            # MMR score: balance relevance and diversity
            score = ALPHA * rel - (1 - ALPHA) * div

            if score > best_score:
                best_score, best_i = score, i

        if best_i is not None:
            selected_idx.append(best_i)
            candidate_idx.remove(best_i)

    selected = [phrases[i] for i in selected_idx]
    return selected


def _rules_extract(text: str) -> List[str]:
    """Simple rule-based keyphrase extraction."""
    # Extract tokens including $SYMBOL
    toks = re.findall(r"\$[A-Za-z0-9_]+|[A-Za-z]{2,}", text)
    base = [t.lower() for t in toks]
    base = [t for t in base if t not in STOPWORDS]

    # Deduplicate while preserving order
    seen = set()
    out = []
    for s in base:
        if s not in seen:
            seen.add(s)
            out.append(s)

    return out[: DEFAULT_TOPK or 5]


def _normalize_filter(
    cands: List[str], min_len: int = 2, dedup: bool = True
) -> List[str]:
    """Normalize and filter candidate keyphrases."""
    out, seen = [], set()
    for c in cands:
        s = c.strip().lower()
        # Allow $SYMBOL tokens
        if len(s) < min_len:
            continue
        if s in STOPWORDS:
            continue
        if dedup and s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[: DEFAULT_TOPK or 5]


def extract_keyphrases(text: str) -> List[str]:
    """
    Extract keyphrases from text.

    Uses KBIR with MMR if enabled, otherwise falls back to rules.
    """
    backend = os.getenv("KEYPHRASE_BACKEND", "off")

    if backend == "off":
        return _rules_extract(text)

    if backend == "kbir":
        topk = 8 if len(text) < 64 else DEFAULT_TOPK
        phrases = _kbir_extract(text, topk=topk)
        phrases = _normalize_filter(
            phrases, min_len=DEFAULT_MIN_LEN, dedup=DEFAULT_DEDUP
        )

        if not phrases and FALLBACK_ON_EMPTY:
            LOGGER.info("KBIR returned empty, falling back to rules")
            return _rules_extract(text)

        return phrases

    return _rules_extract(text)
