"""
HuggingFace batch client with degradation statistics.
Supports both local transformers.pipeline and remote InferenceClient backends.
"""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class HfClient:
    """Unified HuggingFace client for sentiment analysis with batch support and degradation."""

    def __init__(
        self, *, backend: Optional[str] = None, model_id: Optional[str] = None
    ):
        """Initialize HfClient with backend selection and configuration."""
        self.backend = (backend or os.getenv("HF_BACKEND", "local")).lower()
        self.model_id = model_id or os.getenv(
            "HF_MODEL", "cardiffnlp/twitter-roberta-base-sentiment"
        )
        self.timeout_s = float(int(os.getenv("HF_TIMEOUT_MS", "1800"))) / 1000.0
        self.batch_size = int(os.getenv("HF_BATCH_SIZE", "8"))
        self.max_retries = int(os.getenv("HF_MAX_RETRIES", "2"))
        self.concurrency = int(os.getenv("HF_CONCURRENCY", "4"))
        self.fail_rate_threshold = float(os.getenv("HF_DEGRADE_FAIL_RATE", "0.3"))
        self.pos_t = float(os.getenv("SENTIMENT_POS_THRESH", "0.25"))
        self.neg_t = float(os.getenv("SENTIMENT_NEG_THRESH", "-0.25"))

        self._clf = None
        self._client = None
        self._id2label = None
        self._init_backend()

    def _init_backend(self):
        """Initialize the selected backend (local or inference)."""
        if self.backend == "local":
            from transformers import pipeline

            self._clf = pipeline(
                "text-classification",
                model=self.model_id,
                top_k=None,  # Return all scores (replaces deprecated return_all_scores)
                truncation=True,
                max_length=512,
                padding=True,
            )
            # Get id2label from model config
            if hasattr(self._clf, "model") and hasattr(self._clf.model, "config"):
                self._id2label = getattr(self._clf.model.config, "id2label", None)
        else:  # inference backend
            from huggingface_hub import InferenceClient

            self._client = InferenceClient(model=self.model_id, timeout=self.timeout_s)
            self._id2label = None  # Will normalize from returned labels

    def _norm_probs(self, triples: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Normalize label names to standard format.
        triples: [{'label': 'NEGATIVE', 'score': ...}, {'label': 'NEUTRAL', ...}, ...]
        """
        probs = {"pos": 0.0, "neu": 0.0, "neg": 0.0}

        for item in triples:
            label_lower = item["label"].lower()
            score = float(item["score"])

            if "positive" in label_lower or label_lower == "pos":
                probs["pos"] = score
            elif "negative" in label_lower or label_lower == "neg":
                probs["neg"] = score
            elif "neutral" in label_lower or label_lower == "neu":
                probs["neu"] = score

        return probs

    def _to_item(
        self, probs: Dict[str, float], degraded: bool = False
    ) -> Dict[str, Any]:
        """Convert probabilities to standardized output format."""
        score = max(-1.0, min(1.0, float(probs["pos"]) - float(probs["neg"])))

        if score >= self.pos_t:
            label = "pos"
        elif score <= self.neg_t:
            label = "neg"
        else:
            label = "neu"

        out = {"label": label, "score": score, "probs": probs}

        if degraded:
            out["degrade"] = "HF_off"

        return out

    def predict_sentiment_one(self, text: str) -> Dict[str, Any]:
        """
        Predict sentiment for a single text.

        Returns:
            {
                "label": "pos|neu|neg",
                "score": float in [-1, 1],
                "probs": {"pos": float, "neu": float, "neg": float},
                "degrade": "HF_off" | None  # Only present when degraded
            }
        """
        return self.predict_sentiment_batch([text])[0]

    def predict_sentiment_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """
        Predict sentiment for a batch of texts.

        Returns:
            List of dicts with same structure as predict_sentiment_one.
            All items will have degrade="HF_off" if batch failure rate exceeds threshold.
        """
        t0 = time.time()
        fails = 0
        results: List[Optional[Dict[str, Any]]] = [None] * len(texts)

        if self.backend == "local":
            # Local transformers pipeline handles batch natively
            try:
                raw = self._clf(texts, batch_size=self.batch_size)
                for i, triples in enumerate(raw):
                    probs = self._norm_probs(triples)
                    results[i] = self._to_item(probs, degraded=False)
            except Exception as e:
                # If batch fails, mark all as failed
                fails = len(texts)
                for i in range(len(texts)):
                    results[i] = self._to_item(
                        {"pos": 0.0, "neu": 1.0, "neg": 0.0}, degraded=True
                    )

        else:  # inference backend
            # Manual batching with concurrency and retry
            def call_one(idx_text):
                idx, text = idx_text
                delay = 0.2

                for retry in range(self.max_retries + 1):
                    try:
                        # InferenceClient returns list of classification results
                        raw_results = self._client.text_classification(text)

                        # Convert to our format
                        triples = []
                        for result in raw_results:
                            triples.append(
                                {
                                    "label": (
                                        result.label
                                        if hasattr(result, "label")
                                        else result.get("label", "")
                                    ),
                                    "score": (
                                        result.score
                                        if hasattr(result, "score")
                                        else result.get("score", 0.0)
                                    ),
                                }
                            )

                        probs = self._norm_probs(triples)
                        return idx, self._to_item(probs, degraded=False)

                    except Exception as e:
                        if retry == self.max_retries:
                            return idx, None
                        time.sleep(delay)
                        delay *= 2

                return idx, None

            # Execute with thread pool
            with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                futures = [
                    executor.submit(call_one, (i, text)) for i, text in enumerate(texts)
                ]

                for future in as_completed(futures):
                    idx, item = future.result()
                    results[idx] = item

            # Count failures and provide fallback
            for i, v in enumerate(results):
                if v is None:
                    fails += 1
                    results[i] = self._to_item(
                        {"pos": 0.0, "neu": 1.0, "neg": 0.0}, degraded=True
                    )

        # Calculate failure rate and apply batch-wide degradation if needed
        fail_rate = (fails / len(texts)) if len(texts) > 0 else 0.0
        degraded = fail_rate > self.fail_rate_threshold

        if degraded:
            # Mark all results as degraded
            for i in range(len(results)):
                if results[i] is not None:
                    results[i]["degrade"] = "HF_off"

        # Structured logging
        elapsed_ms = int((time.time() - t0) * 1000)
        log.info(
            {
                "ts": time.time(),
                "comp": "hf_client",
                "backend": self.backend,
                "model": self.model_id,
                "batch_size": len(texts),
                "elapsed_ms": elapsed_ms,
                "fail_rate": round(fail_rate, 4),
                "degrade": degraded,
            }
        )

        return results


__all__ = ["HfClient"]
