#!/usr/bin/env python3
"""
Configuration linter for GUIDS project.

Validates:
1. YAML files syntax and structure in rules/
2. Environment variables consistency between .env and .env.example
3. Sensitive information exposure in configuration files
4. Required fields and value ranges

Exit codes:
- 0: All checks passed
- 1: Validation failures found
- 2: Fatal error (file not found, etc.)
"""

import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import yaml


class ConfigLinter:
    """Configuration validation and linting."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.project_root = Path(__file__).resolve().parents[1]

        # Sensitive keywords that should not be hardcoded
        self.sensitive_patterns = [
            "TOKEN",
            "SECRET",
            "KEY",
            "PASSWORD",
            "WEBHOOK",
            "PRIVATE",
            "ACCESS",
            "API_KEY",
        ]

        # Known safe placeholders
        self.safe_placeholders = [
            "__FILL_ME__",
            "your_.*_here",
            "sk-xxxxxxx",
            "0x[0]+",
            "changeme",
            "placeholder",
            "example",
            "default",
        ]

        # Required environment variables (from .env.example)
        self.required_env_vars: Set[str] = set()

        # YAML schema definitions
        self.yaml_schemas = {
            "risk_rules.yml": {
                "required": ["goplus_version"],
                "optional": [
                    "RISK_TAX_RED",
                    "RISK_LP_YELLOW_DAYS",
                    "HONEYPOT_RED",
                    "RISK_MIN_CONFIDENCE",
                    "max_risk_score",
                    "min_risk_score",
                    "default_risk",
                ],
                "types": {
                    "RISK_TAX_RED": (int, float),
                    "RISK_LP_YELLOW_DAYS": (int, float),
                    "HONEYPOT_RED": bool,
                    "RISK_MIN_CONFIDENCE": (int, float),
                    "max_risk_score": (int, float),
                    "min_risk_score": (int, float),
                },
                "ranges": {
                    "RISK_TAX_RED": (0, 100),
                    "RISK_LP_YELLOW_DAYS": (0, 365),
                    "RISK_MIN_CONFIDENCE": (0, 1),
                    "max_risk_score": (0, 1000),
                    "min_risk_score": (0, 1000),
                },
            },
            "onchain.yml": {
                "required": ["windows", "thresholds", "verdict"],
                "types": {"windows": list, "thresholds": dict, "verdict": dict},
            },
            "rules.yml": {
                "required": ["groups", "scoring", "missing_map"],
                "types": {
                    "groups": list,  # Changed from dict to list
                    "scoring": dict,
                    "missing_map": dict,
                },
            },
            "topic_merge.yml": {
                "required": [],  # No strict requirements
                "optional": ["merge_rules", "similarity_threshold"],
                "types": {"similarity_threshold": (int, float)},
                "ranges": {"similarity_threshold": (0, 1)},
            },
        }

    def lint_all(self) -> bool:
        """Run all lint checks."""
        print("Starting configuration lint...")

        # 1. Check YAML files
        print("\n[1/3] Checking YAML files...")
        self._check_yaml_files()

        # 2. Check environment variables
        print("\n[2/3] Checking environment variables...")
        self._check_env_vars()

        # 3. Check for sensitive information
        print("\n[3/3] Scanning for sensitive information...")
        self._check_sensitive_info()

        # Report results
        return self._report_results()

    def _check_yaml_files(self):
        """Validate all YAML files in rules/ directory."""
        rules_dir = self.project_root / "rules"

        if not rules_dir.exists():
            self.errors.append(f"Rules directory not found: {rules_dir}")
            return

        yaml_files = list(rules_dir.glob("*.yml"))

        if not yaml_files:
            self.warnings.append(f"No YAML files found in {rules_dir}")
            return

        for yaml_file in yaml_files:
            # Skip temporary and example files
            if yaml_file.name.endswith(".tmp") or ".example." in yaml_file.name:
                continue

            self._validate_yaml_file(yaml_file)

    def _validate_yaml_file(self, filepath: Path):
        """Validate a single YAML file."""
        try:
            # Check file readability
            if not filepath.is_file():
                self.errors.append(f"Not a file: {filepath}")
                return

            # Parse YAML
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                data = yaml.safe_load(content)

            # Check for empty file
            if data is None:
                self.warnings.append(f"Empty YAML file: {filepath.name}")
                return

            # Validate against schema if defined
            if filepath.name in self.yaml_schemas:
                self._validate_yaml_schema(filepath.name, data)

            # Check for common YAML issues
            self._check_yaml_common_issues(filepath.name, content)

        except yaml.YAMLError as e:
            self.errors.append(f"YAML parse error in {filepath.name}: {str(e)}")
        except Exception as e:
            self.errors.append(f"Error reading {filepath.name}: {str(e)}")

    def _validate_yaml_schema(self, filename: str, data: Any):
        """Validate YAML data against defined schema."""
        schema = self.yaml_schemas[filename]

        if not isinstance(data, dict):
            self.errors.append(f"{filename}: Root must be a dictionary")
            return

        # Check required fields
        for field in schema.get("required", []):
            if field not in data:
                self.errors.append(f"{filename}: Missing required field '{field}'")

        # Check field types
        types = schema.get("types", {})
        for field, expected_type in types.items():
            if field in data:
                value = data[field]
                if not isinstance(value, expected_type):
                    self.errors.append(
                        f"{filename}: Field '{field}' must be {expected_type.__name__}, "
                        f"got {type(value).__name__}"
                    )

        # Check value ranges
        ranges = schema.get("ranges", {})
        for field, (min_val, max_val) in ranges.items():
            if field in data:
                value = data[field]
                if isinstance(value, (int, float)):
                    if not (min_val <= value <= max_val):
                        self.errors.append(
                            f"{filename}: Field '{field}' value {value} "
                            f"out of range [{min_val}, {max_val}]"
                        )

    def _check_yaml_common_issues(self, filename: str, content: str):
        """Check for common YAML issues."""
        lines = content.split("\n")

        for i, line in enumerate(lines, 1):
            # Check for tabs (YAML should use spaces)
            if "\t" in line:
                self.warnings.append(f"{filename}:{i}: Contains tabs (use spaces)")

            # Check for trailing whitespace
            if line.rstrip() != line:
                self.warnings.append(f"{filename}:{i}: Trailing whitespace")

    def _check_env_vars(self):
        """Check environment variable consistency."""
        env_file = self.project_root / ".env"
        env_example = self.project_root / ".env.example"

        if not env_example.exists():
            self.errors.append(".env.example not found")
            return

        # Parse .env.example
        example_vars = self._parse_env_file(env_example)
        self.required_env_vars = set(example_vars.keys())

        # Parse .env if exists
        if env_file.exists():
            actual_vars = self._parse_env_file(env_file)

            # Check for missing required variables
            missing = self.required_env_vars - set(actual_vars.keys())
            for var in sorted(missing):
                # Skip if it's a placeholder value in .env.example
                if example_vars.get(var, "").startswith("__FILL_ME__"):
                    self.warnings.append(f"Missing optional env var: {var}")
                else:
                    self.errors.append(f"Missing required env var: {var}")

            # Check for extra variables not in .env.example
            extra = set(actual_vars.keys()) - self.required_env_vars
            for var in sorted(extra):
                self.warnings.append(f"Extra env var not in .env.example: {var}")
        else:
            self.warnings.append(".env file not found (using defaults)")

    def _parse_env_file(self, filepath: Path) -> Dict[str, str]:
        """Parse an environment file."""
        env_vars = {}

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()

                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue

                    # Parse KEY=VALUE
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()

                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]

                        env_vars[key] = value
                    else:
                        self.warnings.append(
                            f"{filepath.name}:{line_num}: Invalid line format"
                        )

        except Exception as e:
            self.errors.append(f"Error parsing {filepath.name}: {str(e)}")

        return env_vars

    def _check_sensitive_info(self):
        """Scan for hardcoded sensitive information."""
        # Check .env.example for hardcoded secrets
        self._scan_file_for_secrets(self.project_root / ".env.example")

        # Check YAML files
        rules_dir = self.project_root / "rules"
        if rules_dir.exists():
            for yaml_file in rules_dir.glob("*.yml"):
                if not yaml_file.name.endswith(".tmp"):
                    self._scan_file_for_secrets(yaml_file)

        # Check Python files in api/ for hardcoded secrets
        api_dir = self.project_root / "api"
        if api_dir.exists():
            for py_file in api_dir.rglob("*.py"):
                # Skip test files and __pycache__
                if "test" in py_file.name or "__pycache__" in str(py_file):
                    continue
                self._scan_file_for_secrets(py_file)

    def _scan_file_for_secrets(self, filepath: Path):
        """Scan a file for hardcoded sensitive information."""
        if not filepath.exists():
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                lines = content.split("\n")

            for line_num, line in enumerate(lines, 1):
                # Check each sensitive pattern
                for pattern in self.sensitive_patterns:
                    if pattern in line.upper():
                        # Check if it's a real secret or a placeholder
                        if self._looks_like_secret(line, pattern):
                            self.errors.append(
                                f"{filepath.name}:{line_num}: "
                                f"Possible hardcoded secret (contains {pattern})"
                            )

        except Exception as e:
            self.warnings.append(f"Could not scan {filepath.name}: {str(e)}")

    def _looks_like_secret(self, line: str, pattern: str) -> bool:
        """Check if a line contains a real secret (not a placeholder)."""
        # Convert to lowercase for checking
        line_lower = line.lower()

        # Check if it's a comment or documentation
        if line.strip().startswith("#") or line.strip().startswith("//"):
            return False

        # Skip common false positives in code
        false_positives = [
            "event_key",
            "token_ca",
            "api_key",
            "secret_key",
            "private_key",
            "access_token",
            "webhook_url",
            "password_hash",
            "session_key",
            "cache_key",
            "primary_key",
            "foreign_key",
            "sort_key",
            "partition_key",
            "index_key",
            "hash_key",
        ]

        for fp in false_positives:
            if fp in line_lower and not "=" in line:
                return False

        # Check for safe placeholders
        for placeholder in self.safe_placeholders:
            if re.search(placeholder, line_lower):
                return False

        # Check for actual value assignment (for config files)
        if (
            "=" in line
            and not line.strip().startswith("if ")
            and not line.strip().startswith("assert ")
        ):
            parts = line.split("=", 1)
            if len(parts) == 2:
                key, value = parts
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                # Only check if the key matches our sensitive patterns
                key_matches = False
                for sensitive in self.sensitive_patterns:
                    if sensitive in key.upper():
                        key_matches = True
                        break

                if not key_matches:
                    return False

                # Check if value looks like a real secret
                if value and not value.startswith("__") and not value.endswith("__"):
                    # Check for patterns that look like real secrets
                    if any(
                        [
                            value.startswith("sk-") and len(value) > 20,  # OpenAI style
                            value.startswith("pk_") and len(value) > 20,  # Stripe style
                            value.startswith("Bearer ") and len(value) > 20,
                            re.match(r"^[a-fA-F0-9]{40,}$", value),  # Long hex string
                            "hardcode" in value.lower()
                            and len(value) > 10,  # Obvious hardcode
                        ]
                    ):
                        return True

        return False

    def _report_results(self) -> bool:
        """Report lint results and return success status."""
        print("\n" + "=" * 60)
        print("LINT RESULTS")
        print("=" * 60)

        # Report warnings
        if self.warnings:
            print(f"\n⚠️  WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  - {warning}")

        # Report errors
        if self.errors:
            print(f"\n❌ ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"  - {error}")

        # Final status
        print("\n" + "=" * 60)
        if self.errors:
            print("config_lint: FAIL")
            return False
        else:
            print("config_lint: OK")
            return True


def main():
    """Main entry point."""
    linter = ConfigLinter()
    success = linter.lint_all()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
