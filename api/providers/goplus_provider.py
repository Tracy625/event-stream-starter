"""GoPlus security provider with caching and degradation"""

import hashlib
import json
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from api.core.metrics_store import log_json
from api.schemas.security import SecurityResult


class GoPlusProvider:
    """Business aggregation layer for GoPlus security checks"""

    def __init__(self):
        # Load config from environment
        self.backend = os.getenv("SECURITY_BACKEND", "goplus")
        self.cache_ttl_s = int(os.getenv("SECURITY_CACHE_TTL_S", "600"))
        self.db_ttl_s = int(os.getenv("SECURITY_DB_TTL_S", "86400"))
        self.allow_stale = os.getenv("SECURITY_ALLOW_STALE", "true").lower() == "true"
        self.stale_max_s = int(os.getenv("SECURITY_STALE_MAX_S", "172800"))

        # Risk thresholds
        self.risk_tax_red = float(os.getenv("RISK_TAX_RED", "10"))
        self.risk_lp_yellow_days = int(os.getenv("RISK_LP_YELLOW_DAYS", "30"))
        self.honeypot_red = os.getenv("HONEYPOT_RED", "true").lower() == "true"
        self.risk_min_confidence = float(os.getenv("RISK_MIN_CONFIDENCE", "0.6"))

        # In-memory cache (simple dict for now)
        self._memory_cache = {}

        # Lazy init for dependencies
        self._client = None
        self._redis = None
        self._db_engine = None
        self._rules = None

    def _get_client(self):
        """Lazy load GoPlus client; never raise on init failure"""
        if self._client is None and self.backend == "goplus":
            try:
                from api.clients.goplus import GoPlusClient, GoPlusClientError

                self._client = GoPlusClient()
            except Exception as e:  # include GoPlusClientError
                log_json(stage="goplus.error", error=str(e))
                self._client = None
        return self._client

    def _get_redis(self):
        """Lazy load Redis connection"""
        if self._redis is None:
            try:
                import redis

                redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
                self._redis = redis.from_url(redis_url, decode_responses=True)
                # Test connection
                self._redis.ping()
            except Exception as e:
                log_json(stage="goplus.cache.redis_unavailable", error=str(e))
                self._redis = None
        return self._redis

    def _get_db(self):
        """Lazy load database connection (uses POSTGRES_URL)"""
        if self._db_engine is None:
            try:
                from sqlalchemy import create_engine

                dsn = os.getenv("POSTGRES_URL") or os.getenv(
                    "DATABASE_URL", "postgresql://app:app@db:5432/app"
                )
                # normalize driver prefix if provided as postgresql+psycopg2
                dsn = dsn.replace("postgresql+psycopg2://", "postgresql://")
                self._db_engine = create_engine(dsn)
            except Exception as e:
                log_json(stage="goplus.cache.db_unavailable", error=str(e))
                self._db_engine = None
        return self._db_engine

    def _load_rules(self) -> Dict[str, Any]:
        """Load risk rules from registry with hot reload support"""
        if self._rules is not None:
            return self._rules
        try:
            from api.config.hotreload import get_registry

            registry = get_registry()
            # Check for stale configs and reload if needed
            registry.reload_if_stale()
            # Get risk_rules namespace
            self._rules = registry.get_ns("risk_rules")
            if not self._rules:
                log_json(
                    stage="goplus.degrade", reason="rules_missing", backend="rules"
                )
                self._rules = {}
        except Exception as e:
            log_json(stage="goplus.rules.load_error", error=str(e))
            self._rules = {}
        return self._rules

    def _result_from_cached_data(self, data: Dict[str, Any]) -> SecurityResult:
        """Reconstruct SecurityResult from cached payload or evaluate via API schema."""
        if isinstance(data, dict) and data.get("__from_rules__"):
            return SecurityResult(
                risk_label=data.get("risk_label", "unknown"),
                buy_tax=data.get("buy_tax"),
                sell_tax=data.get("sell_tax"),
                lp_lock_days=data.get("lp_lock_days"),
                honeypot=data.get("honeypot"),
                blacklist_flags=data.get("blacklist_flags", []),
                degrade=True,
                cache=True,
                stale=False,
                notes=data.get("notes", ["cached rules result"]),
                raw_response=None,  # Add this to ensure raw_response attribute exists
            )
        # default path: parse API-shaped json
        return self._evaluate_risk(data)

    def _make_cache_key(self, endpoint: str, chain_id: Optional[str], key: str) -> str:
        """Generate cache key"""
        return f"goplus:{endpoint}:{chain_id or '-'}:{key}"

    def _add_ttl_jitter(self, ttl_s: int) -> int:
        """Add 0-10% jitter to TTL to prevent cache stampede"""
        jitter = random.uniform(0, 0.1) * ttl_s
        return int(ttl_s + jitter)

    def get_from_cache(
        self, endpoint: str, chain_id: Optional[str], key: str
    ) -> Optional[Dict[str, Any]]:
        """Get from multi-level cache"""
        cache_key = self._make_cache_key(endpoint, chain_id, key)
        now = time.time()

        # 1. Check memory cache
        if cache_key in self._memory_cache:
            entry = self._memory_cache[cache_key]
            if entry["expires_at"] > now:
                log_json(stage="goplus.cache.hit", source="memory")
                return {"data": entry["data"], "stale": False}
            elif self.allow_stale and (now - entry["expires_at"]) < self.stale_max_s:
                log_json(stage="goplus.cache.hit", source="memory", stale=True)
                return {"data": entry["data"], "stale": True}

        # 2. Check Redis cache
        redis_client = self._get_redis()
        if redis_client:
            try:
                redis_data = redis_client.get(cache_key)
                if redis_data:
                    entry = json.loads(redis_data)
                    if entry["expires_at"] > now:
                        log_json(stage="goplus.cache.hit", source="redis")
                        # Write back to memory
                        self._memory_cache[cache_key] = entry
                        return {"data": entry["data"], "stale": False}
                    elif (
                        self.allow_stale
                        and (now - entry["expires_at"]) < self.stale_max_s
                    ):
                        log_json(stage="goplus.cache.hit", source="redis", stale=True)
                        return {"data": entry["data"], "stale": True}
            except Exception as e:
                log_json(stage="goplus.cache.redis_error", error=str(e))

        # 3. Check DB cache
        db_engine = self._get_db()
        if db_engine:
            try:
                from sqlalchemy import text as sa_text

                with db_engine.connect() as conn:
                    result = conn.execute(
                        sa_text(
                            """
                            SELECT resp_json, expires_at 
                            FROM goplus_cache 
                            WHERE endpoint = :endpoint 
                            AND (chain_id = :chain_id OR (chain_id IS NULL AND :chain_id IS NULL))
                            AND key = :key
                            ORDER BY fetched_at DESC
                            LIMIT 1
                        """
                        ),
                        {"endpoint": endpoint, "chain_id": chain_id, "key": key},
                    ).fetchone()

                    if result:
                        expires_at = result[1].timestamp()
                        if expires_at > now:
                            log_json(stage="goplus.cache.hit", source="db")
                            data = result[0]
                            # Write back to memory and Redis
                            entry = {"data": data, "expires_at": expires_at}
                            self._memory_cache[cache_key] = entry
                            if redis_client:
                                ttl = int(expires_at - now)
                                redis_client.setex(cache_key, ttl, json.dumps(entry))
                            return {"data": data, "stale": False}
                        elif self.allow_stale and (now - expires_at) < self.stale_max_s:
                            log_json(stage="goplus.cache.hit", source="db", stale=True)
                            return {"data": result[0], "stale": True}
            except Exception as e:
                log_json(stage="goplus.cache.db_error", error=str(e))

        log_json(stage="goplus.cache.miss", next="api")
        return None

    def save_to_cache(
        self,
        endpoint: str,
        chain_id: Optional[str],
        key: str,
        data: Dict[str, Any],
        status: str = "success",
        ttl_s: Optional[int] = None,
    ) -> None:
        """Save to multi-level cache"""
        if ttl_s is None:
            ttl_s = self.cache_ttl_s if status == "success" else 60

        ttl_s = self._add_ttl_jitter(ttl_s)
        expires_at = time.time() + ttl_s
        cache_key = self._make_cache_key(endpoint, chain_id, key)
        entry = {"data": data, "expires_at": expires_at}

        # 1. Save to memory
        self._memory_cache[cache_key] = entry

        # 2. Save to Redis
        redis_client = self._get_redis()
        if redis_client:
            try:
                redis_client.setex(cache_key, ttl_s, json.dumps(entry))
            except Exception as e:
                log_json(stage="goplus.cache.redis_save_error", error=str(e))

        # 3. Save to DB
        db_engine = self._get_db()
        if db_engine:
            try:
                from sqlalchemy import text as sa_text

                payload_hash = hashlib.md5(
                    json.dumps(data, sort_keys=True).encode()
                ).hexdigest()
                with db_engine.begin() as conn:
                    conn.execute(
                        sa_text(
                            """
                            INSERT INTO goplus_cache (endpoint, chain_id, key, payload_hash, resp_json, status, fetched_at, expires_at)
                            VALUES (:endpoint, :chain_id, :key, :payload_hash, :resp_json, :status, :fetched_at, :expires_at)
                            """
                        ),
                        {
                            "endpoint": endpoint,
                            "chain_id": chain_id,
                            "key": key,
                            "payload_hash": payload_hash,
                            "resp_json": json.dumps(data),
                            "status": status,
                            "fetched_at": datetime.now(timezone.utc),
                            "expires_at": datetime.fromtimestamp(
                                expires_at, timezone.utc
                            ),
                        },
                    )
            except Exception as e:
                log_json(stage="goplus.cache.db_save_error", error=str(e))

    def _evaluate_risk(self, data: Dict[str, Any]) -> SecurityResult:
        """Evaluate risk from raw data (robust against None / wrong shapes)."""
        # ---- Normalize input to avoid attribute errors ----
        safe_data: Dict[str, Any] = data if isinstance(data, dict) else {}
        raw_result = safe_data.get("result")

        # result can be dict (token addr -> payload) or list; anything else => empty
        if isinstance(raw_result, dict):
            iter_items = list(raw_result.values())
        elif isinstance(raw_result, list):
            iter_items = raw_result
        else:
            iter_items = []

        # helpers
        def _pct_or_none(v):
            """GoPlus sometimes returns tax as fraction (0.05) or string; convert to percent float."""
            try:
                if v is None:
                    return None
                f = float(v)
                # Heuristic: values <= 1 are treated as ratio; >1 are already percent
                return f * 100.0 if f <= 1.0 else f
            except Exception:
                return None

        buy_tax = None
        sell_tax = None
        lp_lock_days = None
        honeypot = None
        blacklist_flags = []

        # ---- Parse each token record defensively ----
        for token_data in iter_items:
            if not isinstance(token_data, dict):
                continue

            bt = _pct_or_none(token_data.get("buy_tax"))
            st = _pct_or_none(token_data.get("sell_tax"))
            # prefer non-None values if multiple entries present
            buy_tax = buy_tax if buy_tax is not None else bt
            sell_tax = sell_tax if sell_tax is not None else st

            # honeypot flag appears as "1" / "0" strings sometimes
            hp = token_data.get("is_honeypot")
            if hp is not None:
                try:
                    honeypot = (str(hp) == "1") if honeypot is None else honeypot
                except Exception:
                    pass

            # LP lock (placeholder; set to 0 if holders present and no lock info)
            if lp_lock_days is None and token_data.get("lp_holders"):
                lp_lock_days = 0

            # collect simple flags
            if str(token_data.get("is_blacklisted", "0")) == "1":
                blacklist_flags.append("blacklisted")
            if str(token_data.get("is_mintable", "0")) == "1":
                blacklist_flags.append("mintable")
            if str(token_data.get("is_proxy", "0")) == "1":
                blacklist_flags.append("proxy")

        # ---- Decide risk label ----
        risk_label = "unknown"
        notes = []

        if honeypot and self.honeypot_red:
            risk_label = "red"
            notes.append("honeypot detected")
        elif buy_tax is not None and buy_tax >= self.risk_tax_red:
            risk_label = "red"
            notes.append(f"high buy tax: {buy_tax}%")
        elif sell_tax is not None and sell_tax >= self.risk_tax_red:
            risk_label = "red"
            notes.append(f"high sell tax: {sell_tax}%")
        elif lp_lock_days is not None and lp_lock_days < self.risk_lp_yellow_days:
            risk_label = "yellow"
            notes.append(f"low LP lock: {lp_lock_days} days")
        elif any(v is not None for v in (buy_tax, sell_tax, honeypot)):
            risk_label = "green"

        log_json(
            stage="goplus.risk",
            label=risk_label,
            honeypot=honeypot,
            buy_tax=buy_tax,
            sell_tax=sell_tax,
            lp_lock_days=lp_lock_days,
        )

        return SecurityResult(
            risk_label=risk_label,
            buy_tax=buy_tax,
            sell_tax=sell_tax,
            lp_lock_days=lp_lock_days,
            honeypot=honeypot,
            blacklist_flags=blacklist_flags,
            notes=notes,
            raw_response=safe_data,
        )

    def _apply_rules(self, address: str) -> SecurityResult:
        """Apply local rules for degraded mode"""
        rules = self._load_rules()
        risk_label = "unknown"
        notes = ["evaluated by local rules"]

        # Check blacklist
        blacklist = rules.get("blacklist", [])
        if address.lower() in [b.lower() for b in blacklist]:
            risk_label = "red"
            notes.append("address blacklisted")

        # Check whitelist
        whitelist = rules.get("whitelist", [])
        if address.lower() in [w.lower() for w in whitelist]:
            risk_label = "green"
            notes.append("address whitelisted")

        log_json(stage="goplus.risk", label=risk_label, source="rules")

        return SecurityResult(
            risk_label=risk_label,
            buy_tax=None,
            sell_tax=None,
            lp_lock_days=None,
            honeypot=None,
            blacklist_flags=[],
            degrade=True,
            cache=False,
            stale=False,
            notes=notes,
            raw_response=None,
        )

    def check_token(self, chain_id: str, address: str) -> SecurityResult:
        """Check token security"""
        # Force rules mode if configured
        if self.backend == "rules":
            log_json(stage="goplus.degrade", reason="backend_rules", backend="rules")
            # try cache first to satisfy acceptance without external deps
            cached = self.get_from_cache("token_security", chain_id, address)
            if cached:
                res = self._result_from_cached_data(cached["data"])
                res.cache = True
                res.stale = cached.get("stale", False)
                return res
            # compute via rules, then cache a lightweight dict for next hit
            res = self._apply_rules(address)
            cache_payload = {
                "__from_rules__": True,
                "risk_label": res.risk_label,
                "buy_tax": res.buy_tax,
                "sell_tax": res.sell_tax,
                "lp_lock_days": res.lp_lock_days,
                "honeypot": res.honeypot,
                "blacklist_flags": getattr(res, "blacklist_flags", []),
                "notes": res.notes,
            }
            self.save_to_cache(
                "token_security",
                chain_id,
                address,
                cache_payload,
                "success",
                self.cache_ttl_s,
            )
            return res

        # Check cache
        cached = self.get_from_cache("token_security", chain_id, address)
        if cached:
            result = self._result_from_cached_data(cached["data"])
            result.cache = True
            result.stale = cached.get("stale", False)
            return result

        # Call API
        try:
            client = self._get_client()
            if not client:
                log_json(stage="goplus.degrade", reason="no_client", backend="rules")
                return self._apply_rules(address)

            data = client.token_security(chain_id, address)

            # Save to cache
            self.save_to_cache(
                "token_security", chain_id, address, data, "success", self.db_ttl_s
            )

            # Evaluate risk
            result = self._evaluate_risk(data)
            log_json(stage="goplus.success", cache_hit=False, risk=result.risk_label)
            return result

        except Exception as e:
            log_json(stage="goplus.error", error=str(e), degrade=True)
            log_json(stage="goplus.degrade", reason="api_error", backend="rules")
            return self._apply_rules(address)

    def check_approval(
        self, chain_id: str, address: str, type: str = "erc20"
    ) -> SecurityResult:
        """Check approval security"""
        cache_key = f"{address}:{type}"

        if self.backend == "rules":
            log_json(stage="goplus.degrade", reason="backend_rules", backend="rules")
            # try cache first to satisfy acceptance without external deps
            cached = self.get_from_cache("approval_security", chain_id, cache_key)
            if cached:
                res = self._result_from_cached_data(cached["data"])
                res.cache = True
                res.stale = cached.get("stale", False)
                return res
            # compute via rules, then cache a lightweight dict for next hit
            res = self._apply_rules(address)
            cache_payload = {
                "__from_rules__": True,
                "risk_label": res.risk_label,
                "buy_tax": res.buy_tax,
                "sell_tax": res.sell_tax,
                "lp_lock_days": res.lp_lock_days,
                "honeypot": res.honeypot,
                "blacklist_flags": getattr(res, "blacklist_flags", []),
                "notes": res.notes,
            }
            self.save_to_cache(
                "approval_security",
                chain_id,
                cache_key,
                cache_payload,
                "success",
                self.cache_ttl_s,
            )
            return res

        cached = self.get_from_cache("approval_security", chain_id, cache_key)
        if cached:
            result = self._result_from_cached_data(cached["data"])
            result.cache = True
            result.stale = cached.get("stale", False)
            return result

        try:
            client = self._get_client()
            if not client:
                log_json(stage="goplus.degrade", reason="no_client", backend="rules")
                return self._apply_rules(address)

            data = client.approval_security(chain_id, address, type=type)
            self.save_to_cache(
                "approval_security",
                chain_id,
                cache_key,
                data,
                "success",
                self.cache_ttl_s,
            )
            result = self._evaluate_risk(data)
            log_json(stage="goplus.success", cache_hit=False, risk=result.risk_label)
            return result
        except Exception as e:
            log_json(stage="goplus.error", error=str(e), degrade=True)
            log_json(stage="goplus.degrade", reason="api_error", backend="rules")
            return self._apply_rules(address)

    def check_address(self, address: str) -> SecurityResult:
        """Check address security"""
        # Force rules mode if configured
        if self.backend == "rules":
            log_json(stage="goplus.degrade", reason="backend_rules", backend="rules")
            cached = self.get_from_cache("address_security", None, address)
            if cached:
                res = self._result_from_cached_data(cached["data"])
                res.cache = True
                res.stale = cached.get("stale", False)
                return res
            res = self._apply_rules(address)
            cache_payload = {
                "__from_rules__": True,
                "risk_label": res.risk_label,
                "buy_tax": res.buy_tax,
                "sell_tax": res.sell_tax,
                "lp_lock_days": res.lp_lock_days,
                "honeypot": res.honeypot,
                "blacklist_flags": getattr(res, "blacklist_flags", []),
                "notes": res.notes,
            }
            self.save_to_cache(
                "address_security",
                None,
                address,
                cache_payload,
                "success",
                self.cache_ttl_s,
            )
            return res

        # Check cache
        cached = self.get_from_cache("address_security", None, address)
        if cached:
            result = self._result_from_cached_data(cached["data"])
            result.cache = True
            result.stale = cached.get("stale", False)
            return result

        # Call API
        try:
            client = self._get_client()
            if not client:
                log_json(stage="goplus.degrade", reason="no_client", backend="rules")
                return self._apply_rules(address)

            data = client.address_security(address)

            # Save to cache
            self.save_to_cache(
                "address_security", None, address, data, "success", self.cache_ttl_s
            )

            # Evaluate risk
            result = self._evaluate_risk(data)
            log_json(stage="goplus.success", cache_hit=False, risk=result.risk_label)
            return result

        except Exception as e:
            log_json(stage="goplus.error", error=str(e), degrade=True)
            log_json(stage="goplus.degrade", reason="api_error", backend="rules")
            return self._apply_rules(address)
