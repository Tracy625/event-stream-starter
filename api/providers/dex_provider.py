"""DEX data provider with DexScreener and GeckoTerminal fallback"""
import os
import json
import time
import requests
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from api.core.metrics_store import log_json


class DexProvider:
    """
    DEX data provider with dual-source fallback.
    Primary: DexScreener
    Secondary: GeckoTerminal
    """
    
    def __init__(self, timeout_s: Optional[float] = None, session: Optional[requests.Session] = None):
        """
        Initialize DEX provider with optional per-instance timeout and injectable session.
        
        Args:
            timeout_s: Request timeout in seconds (overrides env var)
            session: Optional requests session for connection pooling
        """
        # Cache configuration
        cache_ttl = os.getenv("DEX_CACHE_TTL_S") or os.getenv("DEX_CACHE_TTL_SEC", "60")
        if os.getenv("DEX_CACHE_TTL_SEC") and not os.getenv("DEX_CACHE_TTL_S"):
            log_json(stage="dex.config.deprecated", 
                    warning="DEX_CACHE_TTL_SEC is deprecated, use DEX_CACHE_TTL_S")
        self.cache_ttl_s = int(cache_ttl)
        
        # Unified timeout: constructor param > ENV > default 1.5s
        env_timeout = os.getenv("DEX_TIMEOUT_S")
        self.timeout_s = float(timeout_s if timeout_s is not None else (env_timeout or 1.5))
        
        # Use provided session or create new one
        self.session = session or requests.Session()
        
        # API endpoints
        self.dexscreener_base = "https://api.dexscreener.com/latest/dex"
        self.gecko_base = "https://api.geckoterminal.com/api/v2"
        
        # Lazy loaded connections
        self._redis = None
        self._memory_cache = {}
    
    def _get_redis(self):
        """Lazy load Redis connection"""
        if self._redis is None:
            try:
                import redis
                redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
                self._redis = redis.from_url(redis_url, decode_responses=True)
                self._redis.ping()
            except Exception as e:
                log_json(stage="dex.cache.redis_unavailable", error=str(e))
                self._redis = None
        return self._redis
    
    def _normalize_contract(self, contract: str) -> str:
        """Normalize contract address to lowercase"""
        return contract.lower() if contract else ""
    
    @staticmethod
    def _map_err_reason(exc: Exception, status: Optional[int] = None) -> str:
        """Map exception to standard error reason"""
        if isinstance(exc, requests.Timeout):
            return "timeout"
        if isinstance(exc, requests.ConnectionError):
            return "conn_refused"
        if status is not None:
            if 400 <= status < 500:
                return "http_4xx"
            if status >= 500:
                return "http_5xx"
        return "unknown"
    
    @staticmethod
    def _ensure_core_fields(result: dict) -> dict:
        """Ensure all core fields are present in result"""
        result.setdefault("price", result.get("price_usd"))
        result.setdefault("price_usd", result.get("price"))
        result.setdefault("liquidity_usd", None)
        result.setdefault("fdv", None)
        result.setdefault("ohlc", {"m5": None, "h1": None, "h24": None})
        result.setdefault("source", "")
        result.setdefault("cache", False)
        result.setdefault("stale", False)
        result.setdefault("degrade", False)
        result.setdefault("reason", "")
        result.setdefault("notes", [])
        return result
    
    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        """Safe convert to float"""
        try:
            return None if value is None else float(value)
        except (ValueError, TypeError):
            return None
    
    def _get_time_bucket(self) -> int:
        """Get current time bucket for cache key (5 minute buckets)"""
        return int(time.time() // 300)
    
    def _cache_key(self, chain: str, contract: str, bucket: Optional[int] = None) -> str:
        """Generate cache key for snapshot data"""
        ca_norm = self._normalize_contract(contract)
        if bucket is None:
            bucket = self._get_time_bucket()
        return f"dex:snapshot:{chain}:{ca_norm}:{bucket}"
    
    def _last_ok_key(self, chain: str, contract: str) -> str:
        """Generate cache key for last successful data"""
        ca_norm = self._normalize_contract(contract)
        return f"dex:last_ok:{chain}:{ca_norm}"
    
    def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        """Get data from Redis or memory cache"""
        redis = self._get_redis()
        
        if redis:
            try:
                data = redis.get(key)
                if data:
                    return json.loads(data)
            except Exception as e:
                log_json(stage="dex.cache.redis_error", error=str(e), key=key)
        
        # Fall back to memory cache
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if time.time() - entry["ts"] <= self.cache_ttl_s:
                return entry["data"]
        
        return None
    
    def _set_cache(self, key: str, data: Dict[str, Any], ttl: Optional[int] = None):
        """Set data in Redis and memory cache"""
        if ttl is None:
            ttl = self.cache_ttl_s
        
        redis = self._get_redis()
        
        # Always set in memory cache
        self._memory_cache[key] = {
            "ts": time.time(),
            "data": data
        }
        
        if redis:
            try:
                redis.setex(key, ttl, json.dumps(data))
            except Exception as e:
                log_json(stage="dex.cache.redis_write_error", error=str(e), key=key)
    
    def _fetch_dexscreener(self, chain: str, contract: str) -> Optional[Dict[str, Any]]:
        """Fetch data from DexScreener API"""
        try:
            ca_norm = self._normalize_contract(contract)
            chain_map = {
                "eth": "ethereum",
                "ethereum": "ethereum",
                "bsc": "bsc",
                "polygon": "polygon",
                "arbitrum": "arbitrum",
                "optimism": "optimism",
                "base": "base",
                "avalanche": "avalanche"
            }
            
            chain_id = chain_map.get(chain.lower(), chain.lower())
            url = f"{self.dexscreener_base}/tokens/{ca_norm}"
            
            log_json(stage="dex.request", source="dexscreener", chain=chain, contract=ca_norm)
            
            response = self.session.get(url, timeout=self.timeout_s)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract first pair if available
            if data and "pairs" in data and len(data["pairs"]) > 0:
                # Filter by chain if multiple pairs
                pairs = [p for p in data["pairs"] if p.get("chainId", "").lower() == chain_id]
                if not pairs:
                    pairs = data["pairs"]
                
                pair = pairs[0]
                
                result = {
                    "price_usd": float(pair.get("priceUsd", 0) or 0),
                    "liquidity_usd": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                    "fdv": float(pair.get("fdv", 0) or 0),
                    "market_cap": float(pair.get("marketCap", 0) or 0),
                    "volume_24h": float(pair.get("volume", {}).get("h24", 0) or 0),
                    "ohlc": {
                        "m5": {
                            "o": float(pair.get("priceChange", {}).get("m5", 0) or 0),
                            "h": 0, "l": 0, "c": 0
                        },
                        "h1": {
                            "o": float(pair.get("priceChange", {}).get("h1", 0) or 0),
                            "h": 0, "l": 0, "c": 0
                        },
                        "h24": {
                            "o": float(pair.get("priceChange", {}).get("h24", 0) or 0),
                            "h": 0, "l": 0, "c": 0
                        }
                    },
                    "pair_address": pair.get("pairAddress", ""),
                    "base_token": pair.get("baseToken", {}),
                    "quote_token": pair.get("quoteToken", {}),
                    "source": "dexscreener",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                log_json(stage="dex.success", source="dexscreener", 
                        price=result["price_usd"], liquidity=result["liquidity_usd"])
                return result
            
            return None
            
        except requests.Timeout:
            log_json(stage="dex.timeout", source="dexscreener", chain=chain, contract=contract)
            raise
        except (requests.ConnectionError, requests.HTTPError) as e:
            log_json(stage="dex.error", source="dexscreener", error=str(e))
            raise  # Re-raise to let outer handler catch it
        except Exception as e:
            log_json(stage="dex.error", source="dexscreener", error=str(e))
            raise  # Re-raise to let outer handler catch it
    
    def _fetch_geckoterminal(self, chain: str, contract: str) -> Optional[Dict[str, Any]]:
        """Fetch data from GeckoTerminal API"""
        try:
            ca_norm = self._normalize_contract(contract)
            
            # Map chain names to GeckoTerminal network IDs
            chain_map = {
                "eth": "eth",
                "ethereum": "eth",
                "bsc": "bsc",
                "polygon": "polygon",
                "arbitrum": "arbitrum",
                "optimism": "optimism",
                "base": "base",
                "avalanche": "avax"
            }
            
            network = chain_map.get(chain.lower(), chain.lower())
            url = f"{self.gecko_base}/networks/{network}/tokens/{ca_norm}"
            
            log_json(stage="dex.request", source="geckoterminal", chain=chain, contract=ca_norm)
            
            response = self.session.get(url, timeout=self.timeout_s)
            response.raise_for_status()
            
            data = response.json()
            
            if data and "data" in data:
                token_data = data["data"]
                attrs = token_data.get("attributes", {})
                
                result = {
                    "price_usd": float(attrs.get("price_usd", 0) or 0),
                    "liquidity_usd": float(attrs.get("total_reserve_in_usd", 0) or 0),
                    "fdv": float(attrs.get("fdv_usd", 0) or 0),
                    "market_cap": float(attrs.get("market_cap_usd", 0) or 0),
                    "volume_24h": float(attrs.get("volume_usd", {}).get("h24", 0) or 0),
                    "ohlc": {
                        "m5": {"o": 0, "h": 0, "l": 0, "c": 0},
                        "h1": {
                            "o": float(attrs.get("price_change_percentage", {}).get("h1", 0) or 0),
                            "h": 0, "l": 0, "c": 0
                        },
                        "h24": {
                            "o": float(attrs.get("price_change_percentage", {}).get("h24", 0) or 0),
                            "h": 0, "l": 0, "c": 0
                        }
                    },
                    "name": attrs.get("name", ""),
                    "symbol": attrs.get("symbol", ""),
                    "source": "geckoterminal",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                log_json(stage="dex.success", source="geckoterminal",
                        price=result["price_usd"], liquidity=result["liquidity_usd"])
                return result
            
            return None
            
        except requests.Timeout:
            log_json(stage="dex.timeout", source="geckoterminal", chain=chain, contract=contract)
            raise
        except (requests.ConnectionError, requests.HTTPError) as e:
            log_json(stage="dex.error", source="geckoterminal", error=str(e))
            raise  # Re-raise to let outer handler catch it
        except Exception as e:
            log_json(stage="dex.error", source="geckoterminal", error=str(e))
            raise  # Re-raise to let outer handler catch it
    
    def get_snapshot(self, chain: str, contract: str) -> Dict[str, Any]:
        """
        Get DEX snapshot data with fallback and caching.
        
        Args:
            chain: Blockchain network (eth, bsc, polygon, etc.)
            contract: Token contract address
            
        Returns:
            Dict with price, liquidity, metadata and status flags
        """
        ca_norm = self._normalize_contract(contract)
        
        # Check cache first
        cache_key = self._cache_key(chain, contract)
        cached = self._get_from_cache(cache_key)
        
        if cached:
            log_json(stage="dex.cache.hit", chain=chain, contract=ca_norm)
            cached["cache"] = True
            cached["stale"] = False
            cached["degrade"] = False
            return self._ensure_core_fields(cached)
        
        log_json(stage="dex.cache.miss", chain=chain, contract=ca_norm)
        
        # Try primary source (DexScreener)
        result = None
        primary_reason = ""
        
        try:
            result = self._fetch_dexscreener(chain, contract)
            if result:
                result["cache"] = False
                result["stale"] = False
                result["degrade"] = False
                # Only set reason if not already present (avoid overwriting upstream values)
                if "reason" not in result:
                    result["reason"] = ""  # Primary source succeeded, no failure reason
        except requests.HTTPError as e:
            # Calculate reason first, then log
            primary_reason = self._map_err_reason(e, getattr(e.response, "status_code", None))
            log_json(stage="dex.fallback", from_source="dexscreener", to_source="geckoterminal",
                    reason=primary_reason, error=str(e)[:50])
        except (requests.Timeout, requests.ConnectionError) as e:
            # Calculate reason first, then log
            primary_reason = self._map_err_reason(e)
            log_json(stage="dex.fallback", from_source="dexscreener", to_source="geckoterminal",
                    reason=primary_reason, error=str(e)[:50])
        except Exception as e:
            primary_reason = "unknown"
            log_json(stage="dex.fallback", from_source="dexscreener", to_source="geckoterminal",
                    reason=primary_reason, error=str(e)[:50])
        
        # Fallback to secondary source if primary failed
        if not result:
            try:
                result = self._fetch_geckoterminal(chain, contract)
                if result:
                    # Don't let normalize functions set reason
                    result.update({
                        "cache": False,
                        "stale": False,
                        "degrade": False,
                    })
                    # Ensure primary_reason is set if exists
                    if primary_reason:
                        result["reason"] = primary_reason
            except requests.HTTPError as e:
                secondary_reason = self._map_err_reason(e, getattr(e.response, "status_code", None))
                log_json(stage="dex.both_failed", chain=chain, contract=ca_norm,
                        primary_reason=primary_reason, secondary_reason=secondary_reason)
            except (requests.Timeout, requests.ConnectionError) as e:
                secondary_reason = self._map_err_reason(e)
                log_json(stage="dex.both_failed", chain=chain, contract=ca_norm,
                        primary_reason=primary_reason, secondary_reason=secondary_reason)
            except Exception as e:
                secondary_reason = "unknown"
                log_json(stage="dex.both_failed", chain=chain, contract=ca_norm,
                        primary_reason=primary_reason, secondary_reason=secondary_reason,
                        error=str(e)[:50])
        
        # If we have fresh data, cache it
        if result and not result.get("stale"):
            result = self._ensure_core_fields(result)
            # Double-check: ensure primary_reason is preserved after _ensure_core_fields
            if primary_reason and not result.get("reason"):
                result["reason"] = primary_reason
            # Save to short-term cache
            self._set_cache(cache_key, result, self.cache_ttl_s)
            
            # Save to last_ok cache (longer TTL for degradation)
            last_ok_key = self._last_ok_key(chain, contract)
            self._set_cache(last_ok_key, result, 86400)  # 24 hours
            
            return result
        
        # Both sources failed, try to return last_ok
        last_ok_key = self._last_ok_key(chain, contract)
        last_ok = self._get_from_cache(last_ok_key)
        
        if last_ok:
            log_json(stage="dex.degrade", mode="last_ok", chain=chain, contract=ca_norm)
            last_ok = dict(last_ok)  # Make a copy
            src_prev = last_ok.get("source", "")
            last_ok.update({
                "cache": False,
                "stale": True,
                "degrade": True,
                "reason": "both_failed_last_ok",
                "source": "",  # Current no real-time source
                "notes": (last_ok.get("notes") or []) + [f"last_ok_from:{src_prev}"]
            })
            return self._ensure_core_fields(last_ok)
        
        # No data available at all
        log_json(stage="dex.degrade", mode="no_data", chain=chain, contract=ca_norm)
        return {
            "price": None,
            "price_usd": None,
            "liquidity_usd": None,
            "fdv": None,
            "market_cap": None,
            "volume_24h": None,
            "ohlc": {"m5": None, "h1": None, "h24": None},
            "source": "",  # Use empty string, not None
            "cache": False,
            "stale": True,
            "degrade": True,
            "reason": "both_failed_no_cache",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }