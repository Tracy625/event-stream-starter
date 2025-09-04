"""
X KOL polling job for batch tweet collection.

Fetches tweets from configured KOLs, deduplicates, and stores in database.
"""

import os
import hashlib
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import redis
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
# from sqlalchemy.dialects.postgresql import insert  # not used

# Import from api modules (package imports already available in container PYTHONPATH)
from api.clients.x_client import get_x_client
from api.normalize.x import normalize_tweet
from api.metrics import log_json
from api.models import Base, RawPost


def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client for deduplication."""
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    try:
        return redis.from_url(redis_url, decode_responses=True)
    except Exception as e:
        log_json(stage="x.dedup.error", error=str(e))
        return None


_ENGINE = None
_SessionLocal = None

def get_db_session():
    """Get database session (cached SessionLocal)."""
    global _ENGINE, _SessionLocal
    postgres_url = os.getenv("POSTGRES_URL", "postgresql://app:app@db:5432/app")
    if _ENGINE is None or _SessionLocal is None:
        _ENGINE = create_engine(postgres_url, future=True)
        _SessionLocal = sessionmaker(bind=_ENGINE, autoflush=False, autocommit=False)
    return _SessionLocal()


def load_kol_handles() -> List[str]:
    """Load KOL handles from config or environment."""
    # Try loading from config file first
    config_path = "/app/configs/x_kol.yaml"
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                if config and 'kol' in config:
                    handles = [kol['handle'] for kol in config['kol'] if 'handle' in kol]
                    if handles:
                        log_json(stage="x.config", source="yaml", count=len(handles))
                        return handles
        except Exception as e:
            log_json(stage="x.config.error", error=str(e))
    
    # Fall back to environment variable
    handles_env = os.getenv("X_KOL_HANDLES", "")
    if handles_env:
        handles = [h.strip() for h in handles_env.split(",") if h.strip()]
        log_json(stage="x.config", source="env", count=len(handles))
        return handles
    
    log_json(stage="x.config.error", error="No KOL handles configured")
    return []


def compute_fingerprint(source: str, author: str, ts: str, text: str) -> str:
    """Compute deduplication fingerprint."""
    text_prefix = text[:30] if text else ""
    content = f"{source}|{author}|{ts}|{text_prefix}"
    return hashlib.sha1(content.encode()).hexdigest()


def is_duplicate(redis_client: Optional[redis.Redis], tweet_id: str, fingerprint: str) -> bool:
    """Check if tweet is duplicate using Redis."""
    if not redis_client:
        return False
    
    try:
        # Check tweet ID deduplication
        dedup_key = f"dedup:x:{tweet_id}"
        if redis_client.exists(dedup_key):
            log_json(stage="x.dedup.hit", tweet_id=tweet_id, method="id")
            return True
        
        # Check fingerprint deduplication
        fp_key = f"dedup:fp:{fingerprint}"
        if redis_client.exists(fp_key):
            log_json(stage="x.dedup.hit", fp=fingerprint, method="fingerprint")
            return True
        
        # Not a duplicate - set keys with TTL
        redis_client.setex(dedup_key, 14 * 24 * 3600, "1")  # 14 days
        redis_client.setex(fp_key, 14 * 24 * 3600, "1")  # 14 days
        log_json(stage="x.dedup.miss", tweet_id=tweet_id)
        return False
        
    except Exception as e:
        log_json(stage="x.dedup.error", error=str(e))
        return False


def get_cursor(redis_client: Optional[redis.Redis], handle: str) -> Optional[str]:
    """Get last processed tweet ID for a handle."""
    if not redis_client:
        return None
    
    try:
        cursor_key = f"x:cursor:{handle}"
        return redis_client.get(cursor_key)
    except Exception as e:
        log_json(stage="x.cursor.error", error=str(e), handle=handle)
        return None


def set_cursor(redis_client: Optional[redis.Redis], handle: str, tweet_id: str) -> None:
    """Update cursor with latest tweet ID."""
    if not redis_client:
        return
    
    try:
        cursor_key = f"x:cursor:{handle}"
        redis_client.set(cursor_key, tweet_id)
    except Exception as e:
        log_json(stage="x.cursor.error", error=str(e), handle=handle)


def insert_raw_post_x(session, normalized: Dict[str, Any], tweet_id: str) -> bool:
    """Insert normalized tweet into raw_posts table."""
    try:
        # Convert timestamp string to datetime if needed
        ts = normalized.get("ts")
        if isinstance(ts, str):
            # Parse ISO format timestamp
            if 'T' in ts:
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            else:
                ts = datetime.now(timezone.utc)
        
        # Build enhanced urls JSONB (zero-migration; metadata goes in urls field)
        urls_with_meta = {
            "tweet_id": tweet_id,
            "urls": normalized.get("urls", []),
            "extracted_ca": normalized.get("token_ca"),
            "extracted_symbol": normalized.get("symbol"),
        }
        
        # Create raw post record (respect existing schema)
        post = RawPost(
            source="x",
            author=normalized.get("author"),
            text=normalized.get("text"),
            ts=ts,
            urls=urls_with_meta,  # Store metadata in urls JSONB field
            token_ca=normalized.get("token_ca"),
            symbol=normalized.get("symbol"),
            is_candidate=normalized.get("is_candidate", False)
        )
        
        session.add(post)
        session.flush()
        log_json(stage="x.persist.inserted_one", tweet_id=tweet_id)
        return True
        
    except Exception as e:
        log_json(stage="x.persist.error", error=str(e))
        return False


def run_once() -> Dict[str, int]:
    """
    Execute one polling cycle for all configured KOLs.
    
    Returns:
        Statistics dict with keys: fetched, normalized, dedup_hit, inserted
    """
    stats = {
        "fetched": 0,
        "normalized": 0,
        "dedup_hit": 0,
        "inserted": 0
    }
    
    # Load configuration
    handles = load_kol_handles()
    if not handles:
        return stats
    
    # Get clients
    backend = os.getenv("X_BACKEND", "graphql")
    x_client = get_x_client(backend)
    redis_client = get_redis_client()
    
    # Process each handle
    for handle in handles:
        try:
            # Get cursor for incremental fetch
            since_id = get_cursor(redis_client, handle)
            
            # Fetch tweets
            raw_tweets = x_client.fetch_user_tweets(handle, since_id)
            stats["fetched"] += len(raw_tweets)
            
            if not raw_tweets:
                continue
            
            # Track latest tweet ID for cursor
            latest_id_int: Optional[int] = None
            
            # Process tweets
            session = get_db_session()
            try:
                for raw_tweet in raw_tweets:
                    tweet_id = raw_tweet.get("id")
                    if not tweet_id:
                        continue
                    
                    # Update latest ID (numeric compare)
                    try:
                        tid_int = int(tweet_id)
                        if latest_id_int is None or tid_int > latest_id_int:
                            latest_id_int = tid_int
                    except Exception:
                        pass
                    
                    # Normalize tweet
                    normalized = normalize_tweet(raw_tweet)
                    if not normalized:
                        continue
                    
                    stats["normalized"] += 1
                    
                    # Check for duplicates
                    fingerprint = compute_fingerprint(
                        normalized["source"],
                        normalized["author"],
                        normalized.get("ts", ""),
                        normalized.get("text", "")
                    )
                    
                    if is_duplicate(redis_client, tweet_id, fingerprint):
                        stats["dedup_hit"] += 1
                        continue
                    
                    # Insert into database
                    if insert_raw_post_x(session, normalized, tweet_id):
                        stats["inserted"] += 1
                
                # Commit all inserts for this handle
                session.commit()
                
                # Update cursor
                if latest_id_int is not None:
                    set_cursor(redis_client, handle, str(latest_id_int))
                    
            except Exception as e:
                session.rollback()
                log_json(stage="x.persist.error", error=str(e), handle=handle)
            finally:
                session.close()
                
        except Exception as e:
            log_json(stage="x.poll.error", error=str(e), handle=handle)
    
    # Log final stats
    log_json(stage="x.persist.inserted", count=stats["inserted"])
    
    return stats


if __name__ == "__main__":
    # Allow running as module: python -m worker.jobs.x_kol_poll
    stats = run_once()
    print(json.dumps(stats))