"""Rules engine for on-chain feature evaluation."""

import logging
from pathlib import Path
from typing import Optional, Tuple

from api.config.hotreload import get_registry
from api.onchain.dto import OnchainFeature, Rules, Verdict

logger = logging.getLogger(__name__)


def load_rules(path: str = None) -> Rules:
    """
    Load and validate rules from registry with hot reload support.

    Args:
        path: Optional path to YAML rules file (for backwards compatibility)

    Returns:
        Validated Rules object

    Raises:
        ValueError: If rules structure or values are invalid
    """
    try:
        registry = get_registry()
        # Check for stale configs and reload if needed
        registry.reload_if_stale()
        # Get onchain namespace from registry
        data = registry.get_ns("onchain")

        if not data:
            logger.error(f"No onchain rules found in registry")
            raise ValueError(f"No onchain rules found")
    except Exception as e:
        logger.error(f"Failed to load rules: {e}")
        raise ValueError(f"Failed to load rules: {e}")

    # Validate top-level structure
    if not isinstance(data, dict):
        raise ValueError("Rules must be a dictionary")

    allowed_keys = {"windows", "thresholds", "verdict"}
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        raise ValueError(f"Invalid keys in rules: {extra_keys}")

    missing_keys = allowed_keys - set(data.keys())
    if missing_keys:
        raise ValueError(f"Missing required keys: {missing_keys}")

    # Validate windows
    windows = data["windows"]
    if not isinstance(windows, list):
        raise ValueError("windows must be a list")
    if not all(isinstance(w, int) and w > 0 for w in windows):
        raise ValueError("windows must be positive integers")

    # Validate thresholds
    thresholds = data["thresholds"]
    if not isinstance(thresholds, dict):
        raise ValueError("thresholds must be a dictionary")

    for field, labels in thresholds.items():
        if not isinstance(labels, dict):
            raise ValueError(f"thresholds.{field} must be a dictionary")
        if not labels:
            raise ValueError(f"thresholds.{field} cannot be empty")
        for label, value in labels.items():
            if not isinstance(value, (int, float)):
                raise ValueError(f"thresholds.{field}.{label} must be numeric")

    # Validate verdict
    verdict = data["verdict"]
    if not isinstance(verdict, dict):
        raise ValueError("verdict must be a dictionary")

    for verdict_type in ["upgrade_if", "downgrade_if"]:
        if verdict_type not in verdict:
            raise ValueError(f"verdict.{verdict_type} is required")
        conditions = verdict[verdict_type]
        if not isinstance(conditions, list):
            raise ValueError(f"verdict.{verdict_type} must be a list")

        for condition in conditions:
            if not isinstance(condition, str):
                raise ValueError(f"verdict.{verdict_type} conditions must be strings")
            # Validate condition format: field>=label or field<=label
            if ">=" in condition:
                parts = condition.split(">=")
            elif "<=" in condition:
                parts = condition.split("<=")
            else:
                raise ValueError(
                    f"Invalid condition format: {condition}. Only >= and <= are supported"
                )

            if len(parts) != 2:
                raise ValueError(f"Invalid condition format: {condition}")

    logger.info(f"Successfully loaded rules from {path}")
    return Rules(**data)


def _parse_condition(condition: str) -> Optional[Tuple[str, str, str]]:
    """
    Parse a condition string into (field, operator, label).

    Args:
        condition: Condition string like "field>=label"

    Returns:
        Tuple of (field, operator, label) or None if parsing fails
    """
    if ">=" in condition:
        parts = condition.split(">=")
        if len(parts) == 2:
            return (parts[0].strip(), ">=", parts[1].strip())
    elif "<=" in condition:
        parts = condition.split("<=")
        if len(parts) == 2:
            return (parts[0].strip(), "<=", parts[1].strip())
    return None


def _evaluate_condition(
    features: OnchainFeature, condition: str, rules: Rules
) -> Tuple[bool, Optional[str]]:
    """
    Evaluate a single condition.

    Args:
        features: Feature values
        condition: Condition string
        rules: Rules configuration

    Returns:
        Tuple of (result, error_note)
    """
    parsed = _parse_condition(condition)
    if not parsed:
        logger.error(f"Failed to parse condition: {condition}")
        return False, "rule_parse_error"

    field, op, label = parsed

    # Check if field exists in features
    if not hasattr(features, field):
        logger.error(f"Unknown field in condition: {field}")
        return False, "rule_parse_error"

    # Get threshold value
    if field not in rules.thresholds:
        logger.error(f"No thresholds defined for field: {field}")
        return False, "threshold_label_missing"

    if label not in rules.thresholds[field]:
        logger.error(f"Unknown threshold label: {field}.{label}")
        return False, "threshold_label_missing"

    threshold = rules.thresholds[field][label]
    feature_value = getattr(features, field)

    # Perform comparison
    if op == ">=":
        result = feature_value >= threshold
    else:  # op == '<='
        result = feature_value <= threshold

    logger.debug(
        f"Evaluated {field} {op} {label}({threshold}): {feature_value} -> {result}"
    )
    return result, None


def evaluate(features: OnchainFeature, rules: Rules) -> Verdict:
    """
    Evaluate features against rules to produce a verdict.

    Args:
        features: On-chain feature values
        rules: Rules configuration

    Returns:
        Evaluation verdict with decision, confidence, and optional note
    """
    try:
        # Validate window
        if features.window_min not in rules.windows:
            logger.warning(f"Window {features.window_min} not supported")
            return Verdict(
                decision="insufficient", confidence=0.0, note="window_unsupported"
            )

        # Validate feature ranges
        if not (0 <= features.active_addr_pctl <= 1):
            logger.warning(
                f"active_addr_pctl out of range: {features.active_addr_pctl}"
            )
            return Verdict(
                decision="insufficient", confidence=0.0, note="feature_out_of_range"
            )

        if not (0 <= features.top10_share <= 1):
            logger.warning(f"top10_share out of range: {features.top10_share}")
            return Verdict(
                decision="insufficient", confidence=0.0, note="feature_out_of_range"
            )

        if not (0 <= features.self_loop_ratio <= 1):
            logger.warning(f"self_loop_ratio out of range: {features.self_loop_ratio}")
            return Verdict(
                decision="insufficient", confidence=0.0, note="feature_out_of_range"
            )

        if features.growth_ratio < 0:
            logger.warning(f"growth_ratio out of range: {features.growth_ratio}")
            return Verdict(
                decision="insufficient", confidence=0.0, note="feature_out_of_range"
            )

        # Evaluate downgrade conditions (higher priority)
        downgrade_conditions = rules.verdict.get("downgrade_if", [])
        downgrade_results = []
        for condition in downgrade_conditions:
            result, error_note = _evaluate_condition(features, condition, rules)
            if error_note:
                logger.error(f"Condition evaluation failed: {condition}")
                return Verdict(decision="insufficient", confidence=0.0, note=error_note)
            downgrade_results.append(result)

        # Evaluate upgrade conditions
        upgrade_conditions = rules.verdict.get("upgrade_if", [])
        upgrade_results = []
        for condition in upgrade_conditions:
            result, error_note = _evaluate_condition(features, condition, rules)
            if error_note:
                logger.error(f"Condition evaluation failed: {condition}")
                return Verdict(decision="insufficient", confidence=0.0, note=error_note)
            upgrade_results.append(result)

        # Determine verdict (conservative priority)
        if downgrade_results and all(downgrade_results):
            # All downgrade conditions met
            confidence = min(
                1.0, 0.6 + 0.4 * (sum(downgrade_results) / len(downgrade_results))
            )
            logger.info(f"Verdict: downgrade (confidence={confidence})")
            return Verdict(decision="downgrade", confidence=confidence, note=None)
        elif upgrade_results and all(upgrade_results):
            # All upgrade conditions met
            confidence = min(
                1.0, 0.6 + 0.4 * (sum(upgrade_results) / len(upgrade_results))
            )
            logger.info(f"Verdict: upgrade (confidence={confidence})")
            return Verdict(decision="upgrade", confidence=confidence, note=None)
        else:
            # No conditions fully met
            logger.info("Verdict: hold")
            return Verdict(decision="hold", confidence=0.5, note=None)

    except Exception as e:
        logger.error(f"Unexpected error during evaluation: {e}")
        return Verdict(decision="insufficient", confidence=0.0, note="rule_parse_error")
