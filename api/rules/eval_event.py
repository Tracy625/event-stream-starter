"""
Rule engine for evaluating events and signals with hot-reloading support.

Features:
- Hot-reload rules from YAML with TTL caching
- Environment variable substitution
- Safe expression evaluation (whitelist only)
- Source-specific degradation detection
- Thread-safe atomic hot-reload with monotonic time throttling
"""

import os
import re
import threading
import time
import hashlib
import copy
import ast
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import yaml

from api.metrics import log_json

# Safety limits
MAX_FILE_BYTES = 262144  # 256KB
MAX_RULES_COUNT = 200
ALLOWED_ENVS = {"THETA_LIQ", "THETA_VOL", "THETA_SENT"}


class RuleLoader:
    """Loads and caches rules from YAML with thread-safe hot-reload support."""
    
    def __init__(self, rules_path: str = "rules/rules.yml"):
        self.rules_path = Path(rules_path)
        self._ttl_sec = int(os.getenv("RULES_TTL_SEC", "5"))
        
        # Cache structure: {"rules": dict, "version": str, "mtime": float, "etag": str}
        self._cache = None
        self._lock = threading.Lock()
        self._next_check = 0.0  # Next allowed check time (monotonic)
        self._hot_reloaded = False  # Flag for current request
        
    def get(self) -> Tuple[Optional[dict], str, bool]:
        """
        Get rules with hot-reload support.
        
        Returns:
            Tuple of (rules_dict, version_string, hot_reloaded_flag)
        """
        with self._lock:
            now_mono = time.monotonic()
            
            # Throttle checks using monotonic time
            if now_mono < self._next_check:
                # Return cached version without checking file
                if self._cache:
                    return self._cache["rules"], self._cache["version"], False
                # No cache and not time to check yet
                return None, "error", False
            
            # Update next check time regardless of outcome
            self._next_check = now_mono + self._ttl_sec
            
            # Try to reload rules
            hot_reloaded = self._try_reload()
            
            # Return current cache state
            if self._cache:
                return self._cache["rules"], self._cache["version"], hot_reloaded
            
            # No valid cache available
            return None, "error", False
    
    def _try_reload(self) -> bool:
        """
        Try to reload rules from file.
        
        Returns:
            True if rules were successfully reloaded, False otherwise.
        """
        try:
            # Check if file exists
            if not self.rules_path.exists():
                log_json("rules.file_missing", 
                        path=str(self.rules_path),
                        module="api.rules.eval_event")
                return False
            
            # Get file stats
            stat = self.rules_path.stat()
            current_mtime = stat.st_mtime
            file_size = stat.st_size
            
            # Check file size limit
            if file_size > MAX_FILE_BYTES:
                log_json("rules.reload_error",
                        hot_reload=False,
                        error=f"File too large: {file_size} > {MAX_FILE_BYTES}",
                        reason="file_size_exceeded",
                        module="api.rules.eval_event")
                return False
            
            # If we have cache and mtime hasn't changed, skip reload
            if self._cache and self._cache.get("mtime") == current_mtime:
                return False
            
            # Read file content
            try:
                content = self.rules_path.read_text(encoding="utf-8", errors="strict")
            except (FileNotFoundError, UnicodeDecodeError) as e:
                log_json("rules.reload_error",
                        hot_reload=False,
                        error=f"File read error: {str(e)[:200]}",
                        reason="io_error",
                        module="api.rules.eval_event")
                return False
            
            # Calculate etag
            etag = hashlib.sha256(content.encode()).hexdigest()
            
            # If content hasn't changed, just update mtime
            if self._cache and self._cache.get("etag") == etag:
                self._cache["mtime"] = current_mtime
                return False
            
            # Substitute environment variables (whitelisted only)
            content = self._substitute_env_vars_safe(content)
            
            # Parse YAML
            try:
                rules = yaml.safe_load(content)
            except yaml.YAMLError as e:
                log_json("rules.reload_error",
                        hot_reload=False,
                        error=f"YAML parse error: {str(e)[:200]}",
                        reason="yaml_parse_error",
                        module="api.rules.eval_event")
                return False
            
            # Validate structure and safety
            validation_error = self._validate_rules_comprehensive(rules)
            if validation_error:
                log_json("rules.reload_error",
                        hot_reload=False,
                        error=validation_error[:200],
                        reason="validation_failed",
                        module="api.rules.eval_event")
                return False
            
            # Deep copy to ensure isolation
            new_rules = copy.deepcopy(rules)
            
            # Generate version if not provided
            if "version" not in new_rules or not new_rules["version"]:
                new_rules["version"] = f"filemtime:{int(current_mtime)}"
            
            # Build new cache object
            new_cache = {
                "rules": new_rules,
                "version": new_rules["version"],
                "mtime": current_mtime,
                "etag": etag
            }
            
            # Log successful reload
            old_version = self._cache["version"] if self._cache else None
            log_json("rules.reloaded",
                    new_version=new_cache["version"],
                    hot_reload=old_version is not None,
                    ttl_sec=self._ttl_sec,
                    etag_prefix=etag[:8] if etag else None,
                    module="api.rules.eval_event")
            
            # Atomic replacement
            self._cache = new_cache
            return True
            
        except Exception as e:
            log_json("rules.reload_error",
                    hot_reload=False,
                    error=f"Unexpected error: {str(e)[:200]}",
                    reason="unexpected_error",
                    module="api.rules.eval_event")
            return False
    
    def _substitute_env_vars_safe(self, content: str) -> str:
        """Replace ${ENV_KEY:default} with environment values (whitelisted only)."""
        pattern = r'\$\{([A-Z_]+):([^}]*)\}'
        
        def replacer(match):
            env_key = match.group(1)
            default_value = match.group(2)
            
            # Only allow whitelisted environment variables
            if env_key not in ALLOWED_ENVS:
                return match.group(0)  # Return original if not whitelisted
            
            value = os.getenv(env_key, default_value)
            
            # Try to convert to number if it looks numeric
            try:
                if '.' in value:
                    return str(float(value))
                else:
                    return str(int(value))
            except ValueError:
                return value
        
        return re.sub(pattern, replacer, content)
    
    def _validate_rules_comprehensive(self, rules: Any) -> Optional[str]:
        """
        Comprehensive validation of rules structure and safety.
        
        Returns:
            Error message if validation fails, None if successful.
        """
        # Basic type check
        if not isinstance(rules, dict):
            return "Rules must be a dictionary"
        
        # Check required keys
        required_keys = ["groups", "scoring", "missing_map"]
        for key in required_keys:
            if key not in rules:
                return f"Missing required key: {key}"
        
        # Validate groups structure
        groups = rules.get("groups")
        if isinstance(groups, dict):
            # Convert dict format to list format for compatibility
            groups_list = []
            for name, group_data in groups.items():
                if not isinstance(group_data, dict):
                    return f"Group {name} must be a dictionary"
                group_data["name"] = name
                groups_list.append(group_data)
            rules["groups"] = groups_list
            groups = groups_list
        
        if not isinstance(groups, list):
            return "Groups must be a list or dictionary"
        
        if not groups:
            return "Groups cannot be empty"
        
        # Count total rules
        total_rules = 0
        for group in groups:
            if not isinstance(group, dict):
                return "Each group must be a dictionary"
            
            group_rules = group.get("rules", [])
            if not isinstance(group_rules, list):
                return f"Group {group.get('name', 'unknown')} rules must be a list"
            
            total_rules += len(group_rules)
            
            # Validate each rule's expression safety
            for rule in group_rules:
                if not isinstance(rule, dict):
                    continue
                    
                condition = rule.get("condition") or rule.get("when")
                if condition and not self._validate_expression_safety(condition):
                    return f"Unsafe expression: {condition[:100]}"
        
        # Check total rules limit
        if total_rules > MAX_RULES_COUNT:
            return f"Too many rules: {total_rules} > {MAX_RULES_COUNT}"
        
        # Validate scoring structure
        scoring = rules.get("scoring", {})
        if not isinstance(scoring, dict):
            return "Scoring must be a dictionary"
        
        thresholds = scoring.get("thresholds", {})
        if not isinstance(thresholds, dict):
            return "Scoring thresholds must be a dictionary"
        
        # Check for required thresholds
        if "opportunity" not in thresholds and "caution" not in thresholds:
            return "Must define at least opportunity or caution threshold"
        
        # Validate missing_map
        missing_map = rules.get("missing_map", {})
        if not isinstance(missing_map, dict):
            return "Missing map must be a dictionary"
        
        # Should have at least basic missing sources
        required_sources = {"dex", "hf", "goplus"}
        if not any(src in missing_map for src in required_sources):
            return f"Missing map should define at least one of: {required_sources}"
        
        return None
    
    def _validate_expression_safety(self, expression: str) -> bool:
        """
        Validate that an expression is safe to evaluate.
        
        Only allows whitelisted fields and operators.
        """
        # Skip validation if expression contains unreplaced env vars
        # (These will be replaced during substitution)
        if "${" in expression:
            return True
            
        try:
            # Parse the expression into AST
            tree = ast.parse(expression, mode='eval')
            
            # Check all nodes in the AST
            for node in ast.walk(tree):
                # Reject function calls
                if isinstance(node, ast.Call):
                    return False
                
                # Reject attribute access
                if isinstance(node, ast.Attribute):
                    return False
                
                # Reject names starting with underscore
                if isinstance(node, ast.Name):
                    if node.id.startswith('_'):
                        return False
                
                # Reject imports
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    return False
                
                # Reject lambda
                if isinstance(node, ast.Lambda):
                    return False
                
                # Reject comprehensions
                if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                    return False
            
            return True
            
        except SyntaxError:
            return False


class RuleEvaluator:
    """Evaluates rules against event and signal data."""
    
    # Whitelist of allowed fields for expressions
    ALLOWED_FIELDS = {
        "goplus_risk", "buy_tax", "sell_tax", "lp_lock_days",
        "dex_liquidity", "dex_volume_1h", "heat_slope", 
        "last_sentiment_score"
    }
    
    def __init__(self, loader: Optional[RuleLoader] = None):
        self.loader = loader or RuleLoader()
    
    def evaluate(self, signals_row: dict, events_row: dict) -> dict:
        """
        Evaluate rules against signal and event data.
        
        Returns:
            dict with score, level, reasons, missing sources, etc.
        """
        # Get rules using new get() method if available, otherwise fall back
        if hasattr(self.loader, 'get'):
            # New interface: get() returns (rules, version, hot_reloaded)
            rules, version, hot_reloaded = self.loader.get()
        else:
            # Backward compatibility: load_rules() returns rules dict
            rules = self.loader.load_rules()
            version = rules.get("version", "unknown") if rules else "error"
            hot_reloaded = False
        
        if not rules:
            return {
                "score": 0.0,
                "level": "observe",
                "reasons": ["规则加载失败"],
                "all_reasons": ["规则加载失败"],
                "missing": [],
                "rules_version": version,
                "hot_reloaded": hot_reloaded,
                "refine_used": False
            }
        
        # Merge data for evaluation
        eval_context = {**signals_row, **events_row}
        
        # Check for missing data sources
        missing_sources = self._check_missing_sources(eval_context, rules)
        
        # Evaluate all rules
        rule_results = []
        total_score = 0.0
        
        for group in rules["groups"]:
            group_name = group.get("name", "unknown")
            group_priority = group.get("priority", 0)
            
            for rule in group.get("rules", []):
                # Support both "condition" and "when" field names
                condition = rule.get("condition") or rule.get("when", "")
                score = rule.get("score", 0)
                reason = rule.get("reason", "")
                
                # Evaluate condition
                if condition and self._evaluate_condition(condition, eval_context):
                    total_score += score
                    rule_results.append({
                        "group": group_name,
                        "priority": group_priority,
                        "score": score,
                        "reason": reason
                    })
        
        # Add missing source reasons with higher priority to ensure visibility
        for source in missing_sources:
            missing_info = rules["missing_map"].get(source, {})
            if isinstance(missing_info, str):
                # Support both string and dict format for missing_map
                reason = missing_info
            else:
                reason = missing_info.get("reason", f"{source} 数据缺失") if isinstance(missing_info, dict) else f"{source} 数据缺失"
            
            rule_results.append({
                "group": "missing",
                "priority": 100,  # High priority to ensure it appears in top 3
                "score": 0,
                "reason": reason
            })
        
        # Select top reasons and all reasons
        reasons, all_reasons = self._select_top_reasons(rule_results)
        
        # Optionally refine reasons if enabled
        refine_used = False
        try:
            from api.rules.refiner_adapter import maybe_refine_reasons
            refined_reasons, refine_used = maybe_refine_reasons(reasons)
            if refine_used:
                reasons = refined_reasons
                # Also update all_reasons with refined versions for consistency
                # Replace the first len(reasons) items in all_reasons
                all_reasons = refined_reasons + all_reasons[len(reasons):]
        except ImportError:
            # Refiner adapter not available, continue without refinement
            pass
        
        # Determine level
        level = self._determine_level(total_score, rules["scoring"]["thresholds"])
        
        return {
            "score": total_score,
            "level": level,
            "reasons": reasons,
            "all_reasons": all_reasons,
            "missing": missing_sources,
            "rules_version": version,
            "hot_reloaded": hot_reloaded,
            "refine_used": refine_used
        }
    
    def _check_missing_sources(self, data: dict, rules: dict) -> List[str]:
        """Check which data sources are missing."""
        missing = []
        
        for source, info in rules.get("missing_map", {}).items():
            # Support both string and dict format for missing_map values
            if isinstance(info, str):
                # Simple format: just the reason text
                # Use default conditions for known sources
                if source == "dex":
                    condition = "dex_liquidity is null and dex_volume_1h is null"
                elif source == "hf":
                    condition = "last_sentiment_score is null"
                elif source == "goplus":
                    condition = "goplus_risk is null"
                else:
                    continue
            elif isinstance(info, dict):
                condition = info.get("condition", "")
            else:
                continue
                
            if condition and self._evaluate_condition(condition, data):
                missing.append(source)
        
        return missing
    
    def _evaluate_condition(self, condition: str, context: dict) -> bool:
        """
        Safely evaluate a condition expression.
        Only allows whitelisted operations and fields.
        """
        if not condition:
            return False
        
        try:
            # Make a copy to avoid modifying original
            expr = condition
            
            # Handle "is null" and "is not null" first
            for field in self.ALLOWED_FIELDS:
                # Match field with word boundaries to avoid partial replacements
                pattern = r'\b' + re.escape(field) + r'\b'
                
                # Check for "field is null" pattern
                null_pattern = pattern + r'\s+is\s+null'
                if re.search(null_pattern, expr):
                    value = context.get(field)
                    expr = re.sub(null_pattern, str(value is None), expr)
                    continue
                
                # Check for "field is not null" pattern  
                not_null_pattern = pattern + r'\s+is\s+not\s+null'
                if re.search(not_null_pattern, expr):
                    value = context.get(field)
                    expr = re.sub(not_null_pattern, str(value is not None), expr)
                    continue
                
                # Replace regular field references
                if re.search(pattern, expr):
                    value = context.get(field)
                    if value is None:
                        expr = re.sub(pattern, "None", expr)
                    elif isinstance(value, str):
                        expr = re.sub(pattern, repr(value), expr)
                    else:
                        expr = re.sub(pattern, str(value), expr)
            
            # Evaluate the expression safely
            # Create a restricted namespace
            safe_namespace = {
                "__builtins__": {},
                "None": None,
                "True": True,
                "False": False,
            }
            
            # Evaluate the expression
            result = eval(expr, safe_namespace)
            return bool(result)
            
        except (TypeError, NameError):
            # Expected for None comparisons with numbers - just return False
            return False
        except Exception as e:
            # Log unexpected evaluation errors for debugging
            log_json("rules.eval_error", 
                    condition=condition, 
                    error=str(e),
                    module="api.rules.eval_event")
            return False
    
    def _select_top_reasons(self, rule_results: List[dict]) -> Tuple[List[str], List[str]]:
        """
        Select all unique reasons and top 3 reasons, prioritized and deduplicated.
        
        Returns:
            Tuple of (top_3_reasons, all_reasons)
        """
        # Sort by priority (desc) then by absolute score (desc)
        sorted_results = sorted(
            rule_results,
            key=lambda x: (x["priority"], abs(x["score"])),
            reverse=True
        )
        
        # Collect all unique reasons
        seen_reasons = set()
        all_reasons = []
        
        for result in sorted_results:
            reason = result["reason"]
            if reason and reason not in seen_reasons:
                all_reasons.append(reason)
                seen_reasons.add(reason)
        
        # Top 3 reasons are the first 3 from all_reasons
        top_3_reasons = all_reasons[:3]
        
        return top_3_reasons, all_reasons
    
    def _determine_level(self, score: float, thresholds: dict) -> str:
        """Determine risk level based on score."""
        if score >= thresholds.get("opportunity", 15):
            return "opportunity"
        elif score <= thresholds.get("caution", -5):
            return "caution"
        else:
            return "observe"


# Demo/test function
def demo_evaluate():
    """Demo function to test the rule engine."""
    evaluator = RuleEvaluator()
    
    # DEMO1: Complete data
    demo1_signals = {
        "goplus_risk": "green",
        "buy_tax": 2.0,
        "sell_tax": 2.0,
        "lp_lock_days": 200,
        "dex_liquidity": 600000.0,
        "dex_volume_1h": 150000.0,
        "heat_slope": 1.5
    }
    demo1_events = {
        "last_sentiment_score": 0.8
    }
    
    print("DEMO1 (Complete):")
    result1 = evaluator.evaluate(demo1_signals, demo1_events)
    print(f"  Score: {result1['score']}")
    print(f"  Level: {result1['level']}")
    print(f"  Reasons: {result1['reasons']}")
    print(f"  Missing: {result1['missing']}")
    print()
    
    # DEMO2: Missing DEX data
    demo2_signals = {
        "goplus_risk": "yellow",
        "buy_tax": 5.0,
        "sell_tax": 5.0,
        "lp_lock_days": 60,
        "dex_liquidity": None,
        "dex_volume_1h": None,
        "heat_slope": 0.5
    }
    demo2_events = {
        "last_sentiment_score": 0.5
    }
    
    print("DEMO2 (Missing DEX):")
    result2 = evaluator.evaluate(demo2_signals, demo2_events)
    print(f"  Score: {result2['score']}")
    print(f"  Level: {result2['level']}")
    print(f"  Reasons: {result2['reasons']}")
    print(f"  Missing: {result2['missing']}")
    print()
    
    # DEMO3: Missing HF sentiment
    demo3_signals = {
        "goplus_risk": "red",
        "buy_tax": 15.0,
        "sell_tax": 15.0,
        "lp_lock_days": 10,
        "dex_liquidity": 30000.0,
        "dex_volume_1h": 5000.0,
        "heat_slope": -0.5
    }
    demo3_events = {
        "last_sentiment_score": None
    }
    
    print("DEMO3 (Missing HF):")
    result3 = evaluator.evaluate(demo3_signals, demo3_events)
    print(f"  Score: {result3['score']}")
    print(f"  Level: {result3['level']}")
    print(f"  Reasons: {result3['reasons']}")
    print(f"  Missing: {result3['missing']}")


if __name__ == "__main__":
    # Run demo
    demo_evaluate()