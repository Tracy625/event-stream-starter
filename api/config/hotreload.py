"""
Hot configuration reload kernel for rules/*.yml files.

Supports atomic replacement, thread safety, SIGHUP support, and a killswitch option.
"""

import hashlib
import os
import re
import signal
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import copy
import yaml

from api.core.metrics_store import log_json


class HotConfigRegistry:
    """
    Registry for hot-reloading YAML configuration files with atomic replacement.

    Features:
    - TTL-based periodic scanning with mtime/sha1 change detection
    - SIGHUP signal handler for immediate refresh
    - Atomic replacement with RCU-style reads (lock-free reads)
    - Thread-safe with minimal write locking
    - Fail-safe: parse errors keep old version
    - Per-namespace loading with file-to-namespace mapping
    """

    def __init__(
        self,
        files: List[str],
        ttl_seconds: int = 60,
        rules_dir: str = "rules"
    ):
        """
        Initialize the hot config registry.

        Args:
            files: List of YAML file names (e.g., ["thresholds.yml", "kol.yml"])
            ttl_seconds: Time between automatic reload checks
            rules_dir: Directory containing the YAML files
        """
        self.files = files
        self.ttl_seconds = max(1, ttl_seconds)  # Min 1 second
        self.rules_dir = Path(rules_dir)

        # Configuration state (RCU-style snapshot)
        self._config_snapshot: Dict[str, Any] = {}
        self._version_sha: str = ""
        self._last_success_ts: float = 0.0

        # File tracking
        self._file_states: Dict[str, Dict[str, Any]] = {}

        # Thread safety
        self._read_lock = threading.RLock()  # For snapshot reads (mostly unused due to RCU)
        self._write_lock = threading.Lock()  # For updates
        self._last_check_ts = 0.0
        self._min_cooldown = 1.0  # Minimum 1 second between checks

        # Metrics
        self._reload_count = 0
        self._reload_errors = 0

        # Hot reload switch
        self._enabled = os.getenv("CONFIG_HOTRELOAD_ENABLED", "true").lower() == "true"

        # Initial load (fail-fast on startup)
        if not self._initial_load():
            raise RuntimeError(f"[hotreload] Failed initial config load from {self.rules_dir}")

    def _initial_load(self) -> bool:
        """
        Perform initial load of all configuration files.
        Must succeed for system to start.
        """
        new_configs = {}
        file_states = {}

        for filename in self.files:
            ns = self._filename_to_namespace(filename)
            if not ns:
                log_json(
                    stage="config.reload.error",
                    ns=filename,
                    reason="invalid_filename",
                    message=f"[hotreload] Skipping invalid filename: {filename}"
                )
                continue

            filepath = self.rules_dir / filename

            if not filepath.exists():
                log_json(
                    stage="config.reload.error",
                    ns=ns,
                    reason="file_not_found",
                    message=f"[hotreload] File not found: {filepath}"
                )
                # Initial load is lenient about missing files
                continue

            try:
                # Read and parse file
                content = filepath.read_text(encoding="utf-8")
                parsed = yaml.safe_load(content)

                if parsed is None:
                    parsed = {}

                # Calculate checksums
                sha1 = hashlib.sha1(content.encode()).hexdigest()
                mtime = filepath.stat().st_mtime

                # Store config and state
                new_configs[ns] = parsed
                file_states[filename] = {
                    "mtime": mtime,
                    "sha1": sha1,
                    "filepath": str(filepath)
                }

                log_json(
                    stage="config.applied",
                    ns=ns,
                    sha=sha1[:8],
                    message=f"[hotreload] Loaded {ns} from {filename}"
                )

            except Exception as e:
                log_json(
                    stage="config.reload.error",
                    ns=ns,
                    reason="parse_error",
                    error=str(e)[:200],
                    message=f"[hotreload] Failed to parse {filepath}: {e}"
                )
                # Initial load must fail if any file can't be parsed
                return False

        # Atomic replacement
        with self._write_lock:
            self._config_snapshot = new_configs
            self._file_states = file_states
            self._version_sha = self._calculate_version()
            self._last_success_ts = time.time()

        return True

    def _filename_to_namespace(self, filename: str) -> Optional[str]:
        """
        Convert filename to namespace.
        Only allows [-_a-z0-9] filenames.

        Examples:
            thresholds.yml -> thresholds
            kol.yml -> kol
            risk_rules.yml -> risk_rules
        """
        if not filename.endswith(".yml"):
            return None

        stem = filename[:-4]  # Remove .yml

        # Validate filename (prevent directory traversal and weird names)
        if not re.match(r'^[-_a-z0-9]+$', stem):
            return None

        return stem

    def _calculate_version(self) -> str:
        """Calculate combined SHA1 of all loaded configs."""
        combined = ""
        for ns in sorted(self._config_snapshot.keys()):
            file_key = f"{ns}.yml"
            if file_key in self._file_states:
                combined += self._file_states[file_key]["sha1"]

        if not combined:
            return "empty"

        return hashlib.sha1(combined.encode()).hexdigest()[:12]

    def reload_if_stale(self, force: bool = False) -> bool:
        """
        Check if configs need reloading and reload if stale.

        Args:
            force: Force reload regardless of TTL or file changes

        Returns:
            True if configs were reloaded, False otherwise
        """
        # Check if hot reload is enabled
        if not self._enabled and not force:
            return False

        # Throttle checks (unless forced)
        if not force:
            now = time.time()
            with self._write_lock:
                if now - self._last_check_ts < self._min_cooldown:
                    return False
                self._last_check_ts = now

        # Check for changes
        start_ts = time.time()
        changed = self._check_and_reload()

        if changed:
            elapsed_ms = int((time.time() - start_ts) * 1000)
            log_json(
                stage="config.reload",
                old_sha=self._version_sha[:8],
                new_sha=self._calculate_version()[:8],
                elapsed_ms=elapsed_ms,
                message=f"[hotreload] Configuration reloaded in {elapsed_ms}ms"
            )

        return changed

    def _check_and_reload(self) -> bool:
        """
        Check all files for changes and reload if needed.

        Returns:
            True if any configs were reloaded
        """
        # Collect all changes first
        new_configs = {}
        new_file_states = {}
        any_changed = False

        for filename in self.files:
            ns = self._filename_to_namespace(filename)
            if not ns:
                continue

            filepath = self.rules_dir / filename

            # Check if file exists
            if not filepath.exists():
                # File deleted - keep old config if we have it
                if ns in self._config_snapshot:
                    new_configs[ns] = self._config_snapshot[ns]
                    if filename in self._file_states:
                        new_file_states[filename] = self._file_states[filename]
                continue

            try:
                # Check mtime first (cheap)
                stat = filepath.stat()
                current_mtime = stat.st_mtime

                old_state = self._file_states.get(filename, {})
                if old_state.get("mtime") == current_mtime and not any_changed:
                    # No change in mtime, keep old config
                    new_configs[ns] = self._config_snapshot.get(ns, {})
                    new_file_states[filename] = old_state
                    continue

                # Read and check SHA1
                content = filepath.read_text(encoding="utf-8")
                sha1 = hashlib.sha1(content.encode()).hexdigest()

                if old_state.get("sha1") == sha1 and not any_changed:
                    # Content unchanged, just update mtime
                    new_configs[ns] = self._config_snapshot.get(ns, {})
                    new_file_states[filename] = {
                        "mtime": current_mtime,
                        "sha1": sha1,
                        "filepath": str(filepath)
                    }
                    continue

                # Parse the changed file
                start_parse = time.time()
                parsed = yaml.safe_load(content)
                parse_ms = int((time.time() - start_parse) * 1000)

                if parsed is None:
                    parsed = {}

                # Successfully parsed
                new_configs[ns] = parsed
                new_file_states[filename] = {
                    "mtime": current_mtime,
                    "sha1": sha1,
                    "filepath": str(filepath)
                }
                any_changed = True

                log_json(
                    stage="config.applied",
                    ns=ns,
                    old_sha=old_state.get("sha1", "")[:8],
                    new_sha=sha1[:8],
                    elapsed_ms=parse_ms,
                    message=f"[hotreload] Reloaded {ns}"
                )

            except yaml.YAMLError as e:
                # Parse error - keep old config
                self._reload_errors += 1
                log_json(
                    stage="config.reload.error",
                    ns=ns,
                    reason="yaml_parse_error",
                    error=str(e)[:200],
                    message=f"[hotreload] Parse error in {filepath}, keeping old version"
                )
                if ns in self._config_snapshot:
                    new_configs[ns] = self._config_snapshot[ns]
                    if filename in self._file_states:
                        new_file_states[filename] = self._file_states[filename]

            except Exception as e:
                # Other error - keep old config
                self._reload_errors += 1
                log_json(
                    stage="config.reload.error",
                    ns=ns,
                    reason="unexpected_error",
                    error=str(e)[:200],
                    message=f"[hotreload] Error reading {filepath}, keeping old version"
                )
                if ns in self._config_snapshot:
                    new_configs[ns] = self._config_snapshot[ns]
                    if filename in self._file_states:
                        new_file_states[filename] = self._file_states[filename]

        # If nothing changed, return early
        if not any_changed:
            return False

        # Atomic replacement
        with self._write_lock:
            self._config_snapshot = new_configs
            self._file_states = new_file_states
            self._version_sha = self._calculate_version()
            self._last_success_ts = time.time()
            self._reload_count += 1

        return True

    def get_ns(self, ns: str) -> Dict[str, Any]:
        """
        Get configuration for a namespace.
        Returns a deep copy to prevent mutation.

        Args:
            ns: Namespace name (e.g., "thresholds")

        Returns:
            Configuration dict for the namespace (deep copy)
        """
        # RCU-style read - no lock needed for reading snapshot reference
        snapshot = self._config_snapshot

        if ns in snapshot:
            # Return deep copy to prevent caller from modifying internal state
            return copy.deepcopy(snapshot[ns])

        return {}

    def get_path(self, dotted: str, default: Any = None) -> Any:
        """
        Get a value by dotted path (e.g., "thresholds.max_risk").
        Safe access that returns default if path doesn't exist.

        Args:
            dotted: Dotted path (e.g., "thresholds.max_risk")
            default: Default value if path not found

        Returns:
            Value at path or default
        """
        parts = dotted.split(".")
        if not parts:
            return default

        # First part is namespace
        ns = parts[0]
        config = self.get_ns(ns)

        # Navigate the path
        current = config
        for part in parts[1:]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default

        # Deep copy if the result is mutable
        if isinstance(current, (dict, list)):
            return copy.deepcopy(current)

        return current

    def snapshot_version(self) -> str:
        """
        Get the current configuration version (combined SHA1).

        Returns:
            Version string (first 12 chars of combined SHA1)
        """
        return self._version_sha

    def start_signal_handler(self) -> None:
        """
        Install SIGHUP handler for immediate config refresh.
        Should be called once at startup.
        """
        def handle_sighup(signum, frame):
            """Handle SIGHUP signal for config reload."""
            if not self._enabled:
                log_json(
                    stage="config.reload",
                    reason="disabled",
                    message="[hotreload] SIGHUP received but hot reload is disabled"
                )
                return

            log_json(
                stage="config.reload",
                reason="sighup",
                message="[hotreload] SIGHUP received, triggering reload"
            )

            # Force reload
            reloaded = self.reload_if_stale(force=True)

            if reloaded:
                log_json(
                    stage="config.applied",
                    version=self._version_sha[:8],
                    message="[hotreload] Configuration reloaded via SIGHUP"
                )

        # Install handler
        signal.signal(signal.SIGHUP, handle_sighup)
        log_json(
            stage="config.reload",
            message="[hotreload] SIGHUP handler installed"
        )

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get metrics for monitoring.

        Returns:
            Dict with reload counts, errors, version, etc.
        """
        return {
            "config_reload_total": self._reload_count,
            "config_reload_errors_total": self._reload_errors,
            "config_version": self._version_sha,
            "config_last_success_unixtime": int(self._last_success_ts),
            "config_hotreload_enabled": self._enabled
        }


# Global registry instance (singleton)
_registry: Optional[HotConfigRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> HotConfigRegistry:
    """
    Get or create the global configuration registry.

    Returns:
        The global HotConfigRegistry instance
    """
    global _registry

    if _registry is None:
        with _registry_lock:
            if _registry is None:
                # Get configuration from environment
                ttl = int(os.getenv("CONFIG_HOTRELOAD_TTL_SECONDS", "60"))
                rules_dir = os.getenv("RULES_DIR", "rules")

                # Default files to load (only actual existing files)
                files = [
                    "risk_rules.yml",
                    "onchain.yml",
                    "rules.yml",
                    "topic_merge.yml"
                ]

                # Filter to only existing files
                existing_files = []
                rules_path = Path(rules_dir)
                for f in files:
                    if (rules_path / f).exists():
                        existing_files.append(f)

                # Create registry
                _registry = HotConfigRegistry(
                    files=existing_files,
                    ttl_seconds=ttl,
                    rules_dir=rules_dir
                )

                # Start signal handler
                _registry.start_signal_handler()

    return _registry