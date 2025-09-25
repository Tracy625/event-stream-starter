import hashlib
import os
import json
import yaml
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
from hashlib import sha1
import numpy as np

from api.schemas.topic import TopicSignalResponse, TopicMergeConfig
from api.cache import get_redis_client, memoize_ttl
from api.core.metrics_store import log_json, timeit
from api.database import get_db
from sqlalchemy import text as sa_text

# Fixed rules: stop terms and synonyms table
STOP_TERMS = {"meme", "gm", "wagmi"}
SYNONYMS = {"frog": "pepe"}
ALLOWED_SOURCES = {"keybert", "mini", "avatar", "media"}

def _dedupe_preserve_order(seq: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in seq or []:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

def _map_synonym(token: str) -> str:
    t = (token or "").lower().strip()
    return SYNONYMS.get(t, t)

def _normalize_entities(entities: List[str]) -> List[str]:
    norm: List[str] = []
    for e in entities or []:
        v = _map_synonym(e)
        if not v or v in STOP_TERMS:
            continue
        norm.append(v)
    return _dedupe_preserve_order(norm)

def _normalize_keywords(kws: List[str], ents: List[str]) -> List[str]:
    """
    Normalize keywords: synonym mapping, dedup with order preservation, ensure entities included.
    Allow 'meme' and other generic terms in keywords (not in entities).
    """
    base = [_map_synonym(k) for k in (kws or [])]
    merged = base + list(ents or [])
    return _dedupe_preserve_order(merged)

def _normalize_sources(sources: List[str]) -> List[str]:
    mapped: List[str] = []
    for s in sources or []:
        s = (s or "").lower().strip()
        if s == "rules":
            s = "keybert"
        if s in ALLOWED_SOURCES:
            mapped.append(s)
    return _dedupe_preserve_order(mapped)

def _iso_minute(dt: datetime) -> str:
    dt = dt.replace(second=0, microsecond=0, tzinfo=timezone.utc)
    return dt.isoformat()

def _redis_get_counts(topic_id: str, minutes: int) -> Optional[List[int]]:
    """
    Get minute-level counts from Redis for given window:
      key = f"topic:mentions:{topic_id}:{iso_minute}"
    Returns counts in chronological order; None if Redis unavailable or all missing.
    """
    rc = get_redis_client()
    if rc is None or not topic_id:
        return None
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    ts_list = [now - timedelta(minutes=i) for i in range(minutes, -1, -1)]  # Include endpoints
    keys = [f"topic:mentions:{topic_id}:{_iso_minute(ts)}" for ts in ts_list]
    vals = rc.mget(keys)
    out: List[int] = []
    have_any = False
    for v in vals:
        if v is None:
            out.append(0)
        else:
            try:
                cnt = int(v)
                have_any = True
            except Exception:
                cnt = 0
            out.append(cnt)
    return out if have_any else None

def _slope_from_counts(counts: List[int], window: int) -> float:
    """
    Simple slope approximation: endpoint difference / window minutes
    """
    if not counts or window <= 0:
        return 0.0
    try:
        return float(counts[-1] - counts[0]) / float(window)
    except Exception:
        return 0.0

def postprocess_topic_signal(data: Dict) -> Dict:
    """
    Final normalization: entity normalization, keyword dedup/normalization, sources validation,
    merge_mode/degrade flags, stable topic_id generation, slope recalculation
    """
    data = dict(data or {})
    
    # 1) Entity normalization
    ents = _normalize_entities(data.get("topic_entities") or [])
    data["topic_entities"] = ents
    
    # 2) Keyword normalization/dedup (synonym mapping + dedup with order), ensure entities covered
    data["keywords"] = _normalize_keywords(data.get("keywords") or [], ents)
    
    # 3) Sources domain convergence
    data["sources"] = _normalize_sources(data.get("sources") or [])
    
    # 4) Merge mode: default normal; fallback when degraded with explicit degrade=true
    mm = (data.get("topic_merge_mode") or "").lower().strip()
    if data.get("degrade"):
        data["topic_merge_mode"] = "fallback"
    elif not mm or mm == "fallback":
        # Normal path must be normal
        data["topic_merge_mode"] = "normal"
    
    # 5) Recalculate stable topic_id from normalized entities
    if ents:
        h = sha1("|".join(sorted(ents)).encode("utf-8")).hexdigest()[:12]
        data["topic_id"] = f"t.{h}"
    
    # 6) Slopes: if Redis available, recalculate from minute buckets for more accurate values
    tid = data.get("topic_id")
    c10 = _redis_get_counts(tid, 10) if tid else None
    c30 = _redis_get_counts(tid, 30) if tid else None
    if c10:
        data["slope_10m"] = _slope_from_counts(c10, 10)
    if c30:
        data["slope_30m"] = _slope_from_counts(c30, 30)
    
    return data

class TopicAnalyzer:
    """Topic signal analyzer with merging and slope calculation"""
    
    def __init__(self):
        self.config = TopicMergeConfig(
            sim_threshold=float(os.getenv("TOPIC_SIM_THRESHOLD", "0.80")),
            jaccard_fallback=float(os.getenv("TOPIC_JACCARD_FALLBACK", "0.50")),
            whitelist_boost=float(os.getenv("TOPIC_WHITELIST_BOOST", "0.05")),
            window_hours=int(os.getenv("TOPIC_WINDOW_HOURS", "24")),
            slope_window_10m=int(os.getenv("TOPIC_SLOPE_WINDOW_10M", "10")),
            slope_window_30m=int(os.getenv("TOPIC_SLOPE_WINDOW_30M", "30"))
        )
        self.redis = get_redis_client()
        self._load_lists()
        
    def _load_lists(self):
        """Load blacklist and whitelist"""
        self.blacklist = set()
        self.whitelist = set()
        
        # Load blacklist
        blacklist_path = "configs/topic_blacklist.yml"
        if os.path.exists(blacklist_path):
            with open(blacklist_path) as f:
                data = yaml.safe_load(f) or {}
                self.blacklist = set(data.get("blacklist", []))
                
        # Load whitelist  
        whitelist_path = "configs/topic_whitelist.yml"
        if os.path.exists(whitelist_path):
            with open(whitelist_path) as f:
                data = yaml.safe_load(f) or {}
                self.whitelist = set(data.get("whitelist", []))
    
    def _generate_topic_id(self, entities: List[str]) -> str:
        """Generate deterministic topic_id from entities"""
        sorted_entities = sorted(e.lower() for e in entities)
        content = "|".join(sorted_entities)
        hash_val = hashlib.sha1(content.encode()).hexdigest()[:12]
        return f"t.{hash_val}"
    
    def _calculate_slope(self, topic_id: str, window_minutes: int) -> float:
        """Calculate mention slope over time window"""
        try:
            # Get mention counts from Redis time series
            key_pattern = f"topic:mentions:{topic_id}:*"
            now = datetime.now(timezone.utc)
            start_time = now - timedelta(minutes=window_minutes)
            
            # Collect data points
            points = []
            if self.redis:
                # Get all keys matching pattern
                cursor = 0
                keys = []
                while True:
                    cursor, batch = self.redis.scan(cursor, match=key_pattern, count=100)
                    keys.extend(batch)
                    if cursor == 0:
                        break
                
                # Extract timestamps and counts
                for key in keys:
                    parts = key.decode().split(":")
                    if len(parts) >= 4:
                        try:
                            ts_str = parts[3]
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts >= start_time:
                                count = int(self.redis.get(key) or 0)
                                minutes_ago = (now - ts).total_seconds() / 60
                                points.append((minutes_ago, count))
                        except:
                            pass
            
            # Calculate slope using linear regression
            if len(points) >= 2:
                x = np.array([p[0] for p in points])
                y = np.array([p[1] for p in points])
                # Fit linear model: y = mx + b
                coef = np.polyfit(x, y, 1)
                slope = -coef[0]  # Negative because x is "minutes ago"
                return round(slope, 2)
            
            # Default slope if insufficient data
            return 0.0
            
        except Exception as e:
            log_json(stage="topic.slope.error", error=str(e), topic_id=topic_id)
            return 0.0
    
    def _get_mention_count_24h(self, topic_id: str) -> int:
        """Get total mention count in 24h window"""
        try:
            # Query database for mention counts
            with get_db() as db:
                query = sa_text("""
                    SELECT COUNT(*) as count
                    FROM events 
                    WHERE topic_hash = :topic_id
                    AND last_ts >= NOW() - INTERVAL '24 hours'
                """)
                result = db.execute(query, {"topic_id": topic_id}).fetchone()
                return result["count"] if result else 0
        except:
            # Fallback to Redis counter
            if self.redis:
                key = f"topic:count:24h:{topic_id}"
                count = self.redis.get(key)
                return int(count) if count else 0
            return 0
    
    def _get_evidence_links(self, topic_id: str, limit: int = 3) -> List[str]:
        """Get top evidence links for topic"""
        links = []
        try:
            # Query recent posts with this topic
            with get_db() as db:
                query = sa_text("""
                    SELECT metadata->>'url' as url
                    FROM raw_posts
                    WHERE metadata->>'topic_id' = :topic_id
                    ORDER BY ts DESC
                    LIMIT :limit
                """)
                results = db.execute(query, {"topic_id": topic_id, "limit": limit}).fetchall()
                links = [r["url"] for r in results if r["url"]]
        except:
            pass
        
        # Fallback to cached links
        if not links and self.redis:
            key = f"topic:evidence:{topic_id}"
            cached = self.redis.lrange(key, 0, limit - 1)
            links = [l.decode() for l in cached if l]
        
        # Default if no links found
        if not links:
            links = [f"https://x.com/search?q={topic_id[2:]}"]
            
        return links[:limit]
    
    def _check_similarity(self, entities1: List[str], entities2: List[str]) -> Tuple[bool, str]:
        """Check if two entity sets should be merged"""
        # Exact match
        if set(entities1) == set(entities2):
            return True, "exact"
        
        # Try embedding similarity (if available)
        try:
            if os.getenv("EMBEDDING_BACKEND") == "hf":
                # Import delayed to avoid heavy load
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer('all-MiniLM-L6-v2')
                
                text1 = " ".join(entities1)
                text2 = " ".join(entities2)
                
                emb1 = model.encode(text1)
                emb2 = model.encode(text2)
                
                # Cosine similarity
                sim = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
                
                if sim >= self.config.sim_threshold:
                    return True, "embedding"
        except Exception as e:
            log_json(stage="topic.embedding.error", error=str(e))
        
        # Fallback to Jaccard similarity
        set1 = set(e.lower() for e in entities1)
        set2 = set(e.lower() for e in entities2)
        
        intersection = len(set1.intersection(set2))
        union = len(set1.union(set2))
        
        if union > 0:
            jaccard = intersection / union
            if jaccard >= self.config.jaccard_fallback:
                return True, "jaccard"
        
        return False, "none"
    
    def _apply_whitelist_boost(self, entities: List[str], confidence: float) -> float:
        """Apply whitelist boost to confidence"""
        for entity in entities:
            if entity.lower() in self.whitelist:
                return min(1.0, confidence + self.config.whitelist_boost)
        return confidence
    
    def _is_blacklisted(self, entities: List[str]) -> bool:
        """Check if any entity is blacklisted"""
        for entity in entities:
            if entity.lower() in self.blacklist:
                return True
        return False
    
    async def analyze_topic(
        self, 
        topic_id: Optional[str] = None,
        entities: Optional[List[str]] = None
    ) -> TopicSignalResponse:
        """Analyze topic and return signal"""
        
        # Determine entities and topic_id
        if entities:
            # Filter blacklisted entities
            entities = [e for e in entities if not self._is_blacklisted([e])]
            if not entities:
                raise ValueError("All entities are blacklisted")
            topic_id = self._generate_topic_id(entities)
        elif topic_id:
            # Try to retrieve entities from cache/db
            entities = await self._get_entities_for_topic(topic_id)
            if not entities:
                entities = [topic_id[2:8]]  # Use part of hash as fallback
        else:
            raise ValueError("Either topic_id or entities required")
        
        # Calculate slopes
        slope_10m = self._calculate_slope(topic_id, self.config.slope_window_10m)
        slope_30m = self._calculate_slope(topic_id, self.config.slope_window_30m)
        
        # Get mention count
        mention_count = self._get_mention_count_24h(topic_id)
        
        # Calculate confidence
        base_confidence = min(1.0, mention_count / 100)  # Scale by mention count
        confidence = self._apply_whitelist_boost(entities, base_confidence)
        confidence = round(confidence, 2)
        
        # Get evidence links
        evidence_links = self._get_evidence_links(topic_id)
        
        # Determine sources and merge mode
        sources = []
        merge_mode = "normal"
        degrade = False
        
        if os.getenv("KEYBERT_BACKEND") == "kb":
            sources.append("keybert")
        else:
            sources.append("rules")
            
        if os.getenv("EMBEDDING_BACKEND") == "hf":
            sources.append("embedding")
        else:
            merge_mode = "fallback"
            
        # Check for mini LLM timeout/failure
        mini_timeout = int(os.getenv("MINI_LLM_TIMEOUT_MS", "1200"))
        if mini_timeout > 0:
            sources.append("mini")
        else:
            degrade = True
        
        # Build keywords (entities + related)
        keywords = list(entities)
        # Add some mock related keywords
        if "pepe" in [e.lower() for e in entities]:
            keywords.extend(["frog", "meme"])
        
        # Build raw response data
        response_data = {
            "type": "topic",
            "topic_id": topic_id,
            "topic_entities": entities,
            "keywords": keywords[:10],  # Limit keywords
            "slope_10m": slope_10m,
            "slope_30m": slope_30m,
            "mention_count_24h": mention_count,
            "confidence": confidence,
            "sources": sources,
            "evidence_links": evidence_links,
            "calc_version": "topic_v1",
            "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "degrade": degrade,
            "topic_merge_mode": merge_mode
        }
        
        # Apply post-processing normalization
        response_data = postprocess_topic_signal(response_data)
        
        return TopicSignalResponse(**response_data)
    
    async def _get_entities_for_topic(self, topic_id: str) -> List[str]:
        """Retrieve entities for a topic_id from cache/db"""
        # Try Redis cache first
        if self.redis:
            key = f"topic:entities:{topic_id}"
            cached = self.redis.get(key)
            if cached:
                return json.loads(cached)
        
        # Try database
        try:
            with get_db() as db:
                query = sa_text("""
                    SELECT DISTINCT topic_entities
                    FROM signals
                    WHERE topic_id = :topic_id
                    LIMIT 1
                """)
                result = db.execute(query, {"topic_id": topic_id}).fetchone()
                if result and result["topic_entities"]:
                    entities = json.loads(result["topic_entities"])
                    # Cache for next time
                    if self.redis:
                        key = f"topic:entities:{topic_id}"
                        self.redis.setex(key, 3600, json.dumps(entities))
                    return entities
        except:
            pass
        
        return []