#!/usr/bin/env python3
"""Common IO utilities for scripts."""

import json
import os
from typing import List, Dict, Any


def read_jsonl(filepath: str) -> List[Dict[str, Any]]:
    """Read JSONL file and return list of dictionaries."""
    results = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def read_json(filepath: str) -> Dict[str, Any]:
    """Read JSON file and return dictionary."""
    with open(filepath, 'r') as f:
        return json.load(f)


def save_json(data: Dict[str, Any], filepath: str, indent: int = 2) -> None:
    """Save dictionary to JSON file."""
    # Ensure directory exists
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=indent)


def safe_get(data: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Safely get nested value from dictionary using dot notation."""
    keys = path.split('.')
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
            if value is None:
                return default
        else:
            return default
    return value