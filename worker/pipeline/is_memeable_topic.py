import os
import time
import json
import re
from typing import Dict, Any, Tuple, List

from api.core.metrics_store import log_json
from api.cache import get_redis_client

class MemeableTopicDetector:
    """Detect memeable topics using KeyBERT + mini LLM"""
    
    def __init__(self):
        self.backend = os.getenv("KEYBERT_BACKEND", "rules")
        self.mini_llm_timeout = int(os.getenv("MINI_LLM_TIMEOUT_MS", "1200"))
        self.redis = get_redis_client()
        
    def is_memeable(self, text: str, metadata: Dict[str, Any] = None) -> Tuple[bool, List[str], float]:
        """
        Check if text contains memeable topic
        Returns: (is_meme, entities, confidence)
        """
        t0 = time.perf_counter()

        # Try KeyBERT extraction first
        entities = []
        confidence = 0.0
        
        if self.backend == "kb":
            try:
                entities, confidence = self._extract_with_keybert(text)
            except Exception as e:
                log_json(stage="memeable.keybert.error", error=str(e))
                # Fallback to rules
                entities, confidence = self._extract_with_rules(text)
        else:
            entities, confidence = self._extract_with_rules(text)
        
        # If we have entities, try mini LLM verification
        if entities and self.mini_llm_timeout > 0:
            is_meme = self._verify_with_mini_llm(text, entities)
        else:
            # Simple heuristic: if confidence > 0.5 and has entities
            is_meme = len(entities) > 0 and confidence > 0.5
        
        log_json(
            stage="memeable.result",
            is_meme=is_meme,
            entities=entities,
            confidence=confidence,
            backend=self.backend
        )

        # Record timing
        t_ms = int((time.perf_counter() - t0) * 1000)
        log_json(stage="topic.is_memeable.timing", elapsed_ms=t_ms)

        return is_meme, entities, confidence
    
    def _extract_with_keybert(self, text: str) -> Tuple[List[str], float]:
        """Extract keywords using KeyBERT"""
        try:
            from keybert import KeyBERT
            
            # Initialize model (cached after first use)
            kw_model = KeyBERT()
            
            # Extract keywords
            keywords = kw_model.extract_keywords(
                text, 
                keyphrase_ngram_range=(1, 2), 
                stop_words='english',
                top_n=5
            )
            
            # Extract entities and calculate confidence
            entities = []
            total_score = 0.0
            
            for keyword, score in keywords:
                # Filter for potential meme/token names
                if self._is_potential_entity(keyword):
                    entities.append(keyword)
                    total_score += score
            
            confidence = min(1.0, total_score) if entities else 0.0
            
            return entities[:3], confidence
            
        except ImportError:
            log_json(stage="memeable.keybert.missing", fallback="rules")
            return self._extract_with_rules(text)
    
    def _extract_with_rules(self, text: str) -> Tuple[List[str], float]:
        """Rule-based entity extraction"""
        entities = []
        
        # Common meme patterns
        patterns = [
            r'\$([A-Z]{2,10})\b',  # Token symbols like $PEPE
            r'\b([A-Z]{2,10})\s+(?:token|coin|meme)\b',  # "PEPE token"
            r'\b(?:buy|moon|pump|launch)\s+([A-Z]{2,10})\b',  # "buy PEPE"
            r'\b([a-z]+(?:inu|dog|cat|pepe|elon|moon))\b',  # Common meme names
        ]
        
        text_lower = text.lower()
        text_upper = text.upper()
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                entity = match.strip()
                if self._is_potential_entity(entity):
                    entities.append(entity.lower())
        
        # Deduplicate
        entities = list(dict.fromkeys(entities))
        
        # Calculate confidence based on pattern matches
        confidence = min(1.0, len(entities) * 0.3)
        
        return entities[:3], confidence
    
    def _is_potential_entity(self, keyword: str) -> bool:
        """Check if keyword could be an entity name"""
        # Filter out common words
        stopwords = {'the', 'and', 'or', 'but', 'with', 'for', 'new', 'best', 'top'}
        
        keyword_lower = keyword.lower()
        
        # Check length
        if len(keyword) < 2 or len(keyword) > 20:
            return False
        
        # Check if stopword
        if keyword_lower in stopwords:
            return False
        
        # Check if looks like token/meme name
        if re.match(r'^[a-z]+(?:inu|dog|cat|pepe|moon|elon)', keyword_lower):
            return True
        
        # Check if uppercase ticker-like
        if re.match(r'^[A-Z]{2,10}$', keyword):
            return True
        
        # Check if single word (not phrase)
        if ' ' not in keyword and len(keyword) >= 3:
            return True
        
        return False
    
    def _verify_with_mini_llm(self, text: str, entities: List[str]) -> bool:
        """Verify if entities represent a memeable topic using mini LLM"""
        try:
            # Check cache first
            cache_key = f"memeable:llm:{hash(text[:100])}:{','.join(entities)}"
            if self.redis:
                cached = self.redis.get(cache_key)
                if cached:
                    return cached.decode() == "true"
            
            # Import OpenAI (delayed)
            import openai
            
            client = openai.OpenAI(
                api_key=os.getenv("OPENAI_API_KEY"),
                timeout=self.mini_llm_timeout / 1000  # Convert to seconds
            )
            
            prompt = f"""
            Text: {text[:500]}
            Entities: {', '.join(entities)}
            
            Is this about a memecoin or crypto token? Answer only 'yes' or 'no'.
            """
            
            start = time.time()
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
                temperature=0
            )
            
            elapsed_ms = (time.time() - start) * 1000
            
            answer = response.choices[0].message.content.strip().lower()
            is_meme = answer.startswith("yes")
            
            log_json(
                stage="memeable.llm",
                result=is_meme,
                elapsed_ms=elapsed_ms,
                entities=entities
            )
            
            # Cache result
            if self.redis:
                self.redis.setex(cache_key, 3600, "true" if is_meme else "false")
            
            return is_meme
            
        except Exception as e:
            log_json(
                stage="memeable.llm.error",
                error=str(e),
                fallback=True
            )
            # Fallback: assume memeable if has strong indicators
            strong_indicators = ['token', 'coin', 'launch', 'moon', 'pump', '$']
            text_lower = text.lower()
            return any(ind in text_lower for ind in strong_indicators)