"""BigQuery onchain data provider with template support."""

import hashlib
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from google.cloud import bigquery

from api.clients.bq_client import BQClient
from api.core import metrics as metrics_core
from api.utils.cache import RedisCache
from api.utils.logging import log_json

ALLOWED_DEGRADE_REASONS = {
    "cost_guard",
    "template_error",
    "bq_off",
    "upstream_error",
    "dry_run_failed",
}

# Metrics registry (module-level singletons)
METRIC_BQ_QUERY_TOTAL = metrics_core.counter(
    "bq_query_total", "Count of BigQuery operations by template/chain/source/kind"
)

METRIC_BQ_BYTES_SCANNED_TOTAL = metrics_core.counter(
    "bq_bytes_scanned_total", "Total bytes scanned by BigQuery queries"
)

METRIC_BQ_COST_GUARD_HIT = metrics_core.counter(
    "bq_cost_guard_hit_total", "Total BigQuery cost-guard hits"
)

METRIC_BQ_DRY_RUN_FAIL = metrics_core.counter(
    "bq_dry_run_fail_total", "Total BigQuery dry-run failures"
)

METRIC_ONCHAIN_DEGRADE = metrics_core.counter(
    "onchain_degrade_total", "Count of onchain degrade events grouped by reason"
)

METRIC_BQ_DATA_FRESHNESS_LAG = metrics_core.gauge(
    "bq_data_freshness_lag_seconds", "Latest BigQuery freshness lag in seconds"
)

METRIC_BQ_MAX_BYTES = metrics_core.gauge(
    "bq_maximum_bytes_billed_bytes", "Configured BigQuery maximum bytes billed guard"
)

METRIC_BQ_LAST_JOB_BYTES = metrics_core.gauge(
    "bq_last_job_bytes_scanned", "Last BigQuery job bytes scanned"
)

METRIC_BQ_QUERY_LATENCY = metrics_core.histogram(
    "bq_query_latency_seconds",
    "BigQuery query latency in seconds",
    [1, 2, 5, 10, 30, 60],
)


def _label_tpl(template: Optional[str]) -> str:
    if not template:
        return "unknown"
    return template.replace("/", "_")


def _label_chain(chain: Optional[str]) -> str:
    if not chain:
        return "unknown"
    return chain.lower()


def _record_degrade(reason: str) -> None:
    reason_label = reason if reason in ALLOWED_DEGRADE_REASONS else "other"
    METRIC_ONCHAIN_DEGRADE.inc(labels={"reason": reason_label})


class BQSettings(NamedTuple):
    """BigQuery configuration settings."""

    project: str
    location: str
    dataset: str
    timeout_s: int
    max_scanned_gb: float
    onchain_view: Optional[str]  # Card D usage, optional for other scenarios


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Get environment variable with default."""
    v = os.getenv(name)
    return v if v is not None and v != "" else default


def load_bq_settings() -> BQSettings:
    """
    Load unified BigQuery configuration:
      - New variables priority: BQ_PROJECT / BQ_DATASET / BQ_LOCATION / BQ_TIMEOUT_S / BQ_MAX_SCANNED_GB / BQ_ONCHAIN_FEATURES_VIEW
      - Legacy fallback: GCP_PROJECT -> BQ_PROJECT, BQ_DATASET_RO -> BQ_DATASET
    Raises ValueError if critical settings are missing.
    """
    project = _env("BQ_PROJECT") or _env("GCP_PROJECT")
    dataset = _env("BQ_DATASET") or _env("BQ_DATASET_RO")
    location = _env("BQ_LOCATION", "US")
    timeout_s = int(_env("BQ_TIMEOUT_S", "60"))
    max_scanned_gb = float(_env("BQ_MAX_SCANNED_GB", "10"))
    onchain_view = _env("BQ_ONCHAIN_FEATURES_VIEW")  # Card D routes will use this

    missing = []
    if not project:
        missing.append("BQ_PROJECT (or GCP_PROJECT)")
    if not dataset:
        missing.append("BQ_DATASET (or BQ_DATASET_RO)")
    if missing:
        raise ValueError(f"[BQ config] Missing required env: {', '.join(missing)}")

    return BQSettings(
        project=project,
        location=location,
        dataset=dataset,
        timeout_s=timeout_s,
        max_scanned_gb=max_scanned_gb,
        onchain_view=onchain_view,
    )


def make_bq_client(settings: Optional[BQSettings] = None) -> bigquery.Client:
    """
    Create BigQuery Client respecting project and location settings.
    Defaults to using GOOGLE_APPLICATION_CREDENTIALS or Workload Identity.
    """
    settings = settings or load_bq_settings()
    return bigquery.Client(project=settings.project, location=settings.location)


class BQProvider:
    """Onchain data provider using BigQuery."""

    def __init__(self, settings: Optional[BQSettings] = None):
        self.settings = settings or load_bq_settings()
        self.client = BQClient()
        self.templates_dir = (
            Path(__file__).parent.parent.parent.parent / "templates" / "sql"
        )
        self.cache = RedisCache()
        # Surface current guard config
        METRIC_BQ_MAX_BYTES.set(int(self.settings.max_scanned_gb * (1024**3)))

    def run_template(self, name: str, **kwargs) -> Dict | List:
        """
        Run a SQL template with parameters.

        Args:
            name: Template name (without .sql extension)
            **kwargs: Template parameters

        Returns:
            Query results or degraded response
        """
        backend = os.getenv("ONCHAIN_BACKEND", "bq")
        if backend == "off":
            log_json(stage="bq_provider.run_template", backend_off=True, template=name)
            _record_degrade("bq_off")
            return {"degrade": True, "reason": "bq_off"}

        # For business ETH templates, delegate to guarded executor
        if name in (
            "active_addrs_window",
            "token_transfers_window",
            "top_holders_snapshot",
        ):
            return self.execute_template(name, kwargs)

        # Otherwise treat as lightweight inline probe (e.g., freshness_eth, healthz_probe)
        try:
            sql_template = self._get_inline_template(name)
            if not sql_template:
                log_json(
                    stage="bq_provider.run_template",
                    error="template_not_found",
                    template=name,
                )
                _record_degrade("template_error")
                return {
                    "degrade": True,
                    "reason": "template_not_found",
                    "template": name,
                }

            sql = sql_template  # inline templates already have dataset substituted and LIMIT
            log_json(stage="bq_provider.run_template", template=name, params=kwargs)

            # Dry-run using shared helper
            try:
                bytes_scanned = self._dry_run_with_params(
                    sql, [], template=name, chain=kwargs.get("chain"), source="inline"
                )
            except Exception as e:
                log_json(
                    stage="bq_provider.run_template",
                    error="dry_run_failed",
                    template=name,
                    details=str(e),
                )
                _record_degrade("dry_run_failed")
                return {"degrade": True, "reason": "dry_run_failed", "template": name}

            # Cost guard consistent with guarded executor
            max_bytes = int(self.settings.max_scanned_gb * 1024 * 1024 * 1024)
            METRIC_BQ_MAX_BYTES.set(max_bytes)

            if bytes_scanned > max_bytes:
                METRIC_BQ_COST_GUARD_HIT.inc(
                    labels={
                        "tpl": _label_tpl(name),
                        "chain": _label_chain(kwargs.get("chain")),
                    }
                )
                _record_degrade("cost_guard")
                log_json(
                    stage="bq_provider.run_template",
                    cost_guard_hit=True,
                    template=name,
                    bq_bytes_scanned=bytes_scanned,
                )
                return {
                    "degrade": True,
                    "reason": "cost_guard",
                    "bq_bytes_scanned": bytes_scanned,
                    "template": name,
                }
            # Execute with cost cap (no params for inline probes)
            rows = self._execute_with_params(
                sql,
                [],
                max_bytes,
                template=name,
                chain=kwargs.get("chain"),
                source="inline",
            )
            if not rows:
                return {"degrade": True, "reason": "no_data", "template": name}

            # Single-row probe returns dict; others return list
            if len(rows) == 1:
                return rows[0]
            return rows

        except Exception as e:
            log_json(
                stage="bq_provider.run_template",
                error=str(e),
                template=name,
                degrade=True,
            )
            _record_degrade("upstream_error")
            return {"degrade": True, "reason": "provider_error", "template": name}

    def _render_template(self, sql_template: str) -> str:
        """Render template variables for guarded templates."""
        replacements = {
            "BQ_DATASET_RO": self.settings.dataset,
            "BQ_DATASET": self.settings.dataset,
            "BQ_PROJECT": self.settings.project,
            "GCP_PROJECT": self.settings.project,
        }

        def _replace_double(match: re.Match) -> str:
            key = match.group(1)
            return replacements.get(key, match.group(0))

        def _replace_dollar(match: re.Match) -> str:
            key = match.group(1)
            return replacements.get(key, match.group(0))

        sql = re.sub(r"\{\{\s*([A-Z0-9_]+)\s*\}\}", _replace_double, sql_template)
        sql = re.sub(r"\$\{([A-Z0-9_]+)\}", _replace_dollar, sql)
        return sql

    def _get_inline_template(self, name: str) -> Optional[str]:
        """Get inline SQL template for known queries."""
        templates = {
            "freshness_eth": """
                SELECT
                  number AS latest_block,
                  timestamp AS data_as_of
                FROM `{dataset}.blocks`
                ORDER BY number DESC
                LIMIT 1
            """,
            "healthz_probe": """
                SELECT
                  1 AS probe,
                  COUNT(*) AS row_count
                FROM `{dataset}.blocks`
                LIMIT 1
            """,
        }

        template = templates.get(name)
        if template:
            # Inject dataset from settings
            return template.replace("{dataset}", self.settings.dataset)

        return None

    def healthz(self) -> Dict:
        """
        Health check with minimal dry-run probe.

        Returns:
            Health status with dry-run metrics
        """
        backend = os.getenv("ONCHAIN_BACKEND", "bq")
        if backend == "off":
            return {"degrade": True, "reason": "bq_off"}

        try:
            # Use lightweight probe_connectivity method (dry-run only)
            return self.client.probe_connectivity()

        except Exception as e:
            log_json(stage="bq_provider.healthz", error=str(e), degrade=True)
            return {"degrade": True, "reason": "health_check_failed"}

    def freshness(self, chain: str) -> Dict:
        """
        Get freshness data for a specific chain.

        Args:
            chain: Blockchain identifier (e.g., "eth", "polygon")

        Returns:
            Freshness data or degraded response
        """
        backend = os.getenv("ONCHAIN_BACKEND", "bq")
        if backend == "off":
            return {"degrade": True, "reason": "bq_off"}

        # Map chain to template name
        template_map = {"eth": "freshness_eth", "ethereum": "freshness_eth"}

        template = template_map.get(chain.lower())
        if not template:
            log_json(stage="bq_provider.freshness", unsupported_chain=chain)
            return {"degrade": True, "reason": "unsupported_chain", "chain": chain}

        try:
            result = self.run_template(template)

            if isinstance(result, dict):
                if not result.get("degrade"):
                    # Add chain to response
                    result["chain"] = chain

                    # Ensure data_as_of is present
                    if "data_as_of" in result:
                        try:
                            if isinstance(result["data_as_of"], str):
                                data_dt = datetime.fromisoformat(
                                    result["data_as_of"].replace("Z", "+00:00")
                                )
                            else:
                                data_dt = result["data_as_of"]
                            lag_seconds = max(
                                0.0,
                                (datetime.now(timezone.utc) - data_dt).total_seconds(),
                            )
                            METRIC_BQ_DATA_FRESHNESS_LAG.set(
                                lag_seconds, labels={"chain": _label_chain(chain)}
                            )
                        except Exception:
                            pass
                        log_json(
                            stage="bq_provider.freshness",
                            success=True,
                            chain=chain,
                            latest_block=result.get("latest_block"),
                            data_as_of=result.get("data_as_of"),
                        )

                return result

            return {"degrade": True, "reason": "unexpected_result", "chain": chain}

        except Exception as e:
            log_json(
                stage="bq_provider.freshness", error=str(e), chain=chain, degrade=True
            )
            return {"degrade": True, "reason": "freshness_error", "chain": chain}

    def execute_template(self, template: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute SQL template with freshness guard, cost guard, cache, and LINT.

        Args:
            template: Template name (e.g., "active_addrs_window")
            params: Query parameters including address, from_ts, to_ts, etc.

        Returns:
            Response dict with data and metadata
        """
        log_json(stage="bq.execute_template", template=template, params=params)

        # Load template
        template_path = self.templates_dir / "eth" / f"{template}.sql"
        if not template_path.exists():
            log_json(
                stage="bq.execute_template",
                error="template_not_found",
                template=template,
            )
            _record_degrade("template_error")
            return {
                "stale": True,
                "degrade": "template_error",
                "reason": "template_not_found",
                "template": template,
            }

        with open(template_path, "r") as f:
            sql_template = f.read()

        # LINT the template
        lint_result = self._lint_template(sql_template, template)
        if not lint_result["valid"]:
            log_json(
                stage="bq.execute_template",
                lint_failed=True,
                template=template,
                reason=lint_result["reason"],
            )
            _record_degrade("template_error")
            return {
                "stale": True,
                "degrade": "template_error",
                "reason": "lint_failed",
                "template": template,
                "lint_error": lint_result["reason"],
            }

        # Check freshness first
        freshness_result = self._check_freshness()
        data_as_of_lag = freshness_result.get("lag", False)

        # Prepare parameters
        query_params = self._prepare_query_params(params, template)

        # Replace template variables
        sql_rendered = self._render_template(sql_template)
        log_json(stage="bq.sql_preview", template=template, sql_head=sql_rendered[:220])

        # Dry-run for cost estimation
        try:
            try:
                bytes_scanned = self._dry_run_with_params(
                    sql_rendered,
                    query_params,
                    template=template,
                    chain=params.get("chain"),
                    source="template",
                )
                log_json(
                    stage="bq.dry_run",
                    template=template,
                    bq_bytes_scanned=bytes_scanned,
                )
            except Exception as dry_run_error:
                log_json(
                    stage="bq.dry_run",
                    error="dry_run_failed",
                    template=template,
                    details=str(dry_run_error),
                )
                _record_degrade("dry_run_failed")
                return {
                    "degrade": "dry_run_failed",
                    "template": template,
                    "cache_hit": False,
                    "error": str(dry_run_error),
                }

            # Cost guard
            max_bytes = int(self.settings.max_scanned_gb * 1024 * 1024 * 1024)
            METRIC_BQ_MAX_BYTES.set(max_bytes)

            if bytes_scanned > max_bytes:
                METRIC_BQ_COST_GUARD_HIT.inc(
                    labels={
                        "tpl": _label_tpl(template),
                        "chain": _label_chain(params.get("chain")),
                    }
                )
                _record_degrade("cost_guard")
                log_json(
                    stage="bq.query",
                    cost_guard_hit=True,
                    template=template,
                    bq_bytes_scanned=bytes_scanned,
                    max_bytes=max_bytes,
                )
                return {
                    "degrade": "cost_guard",
                    "bq_bytes_scanned": bytes_scanned,
                    "template": template,
                    "cache_hit": False,
                    "data_as_of_lag": False,
                    "approximate": False,
                }

            # Generate cache key AFTER cost guard passes
            cache_key = self._generate_cache_key(template, params, sql_rendered)

            # Check cache AFTER cost guard
            cached = self.cache.get_json(cache_key)
            if cached:
                log_json(stage="bq.cache_hit", template=template, cache_key=cache_key)
                cached["cache_hit"] = True
                cached["data_as_of_lag"] = data_as_of_lag
                return cached

            # Execute query with cost limit
            result = self._execute_with_params(
                sql_rendered,
                query_params,
                max_bytes,
                template=template,
                chain=params.get("chain"),
                source="template",
            )

            # Process results
            response = self._process_template_results(result, template, params)
            response["bq_bytes_scanned"] = bytes_scanned
            response["cache_hit"] = False
            response["data_as_of_lag"] = data_as_of_lag

            # Determine if approximate
            if (
                template == "top_holders_snapshot"
                and "erc20_balances_latest" not in sql_rendered
            ):
                response["approximate"] = True
                response["notes"] = "approximate_balance"
            else:
                response["approximate"] = False

            # Cache the response
            self.cache.set_json(cache_key, response)

            log_json(
                stage="bq.query",
                template=template,
                address=params.get("address"),
                window_minutes=params.get("window_minutes"),
                data_as_of=response.get("data_as_of"),
                data_as_of_lag=data_as_of_lag,
                bq_bytes_scanned=bytes_scanned,
                approximate=response.get("approximate", False),
                cache_hit=False,
            )

            return response

        except Exception as e:
            # Bubble up the dry-run error so caller sees the exact reason
            log_json(stage="bq.execute_template", error=str(e), template=template)
            _record_degrade("upstream_error")
            return {
                "degrade": "dry_run_failed",
                "template": template,
                "cache_hit": False,
                "error": str(e),
            }

    def _lint_template(self, sql: str, template: str) -> Dict[str, Any]:
        """LINT SQL template for required patterns."""
        sql_lower = sql.lower()

        # Check LIMIT (ignore comments by regex word boundary)
        if not re.search(r"\blimit\s+\d+", sql_lower, re.I):
            return {"valid": False, "reason": "missing_limit"}

        # Check for trailing garbage (% or other non-whitespace after last statement)
        if re.search(r"[;]\s*[^;\s]+\s*$", sql, re.M) or sql.rstrip().endswith("%"):
            return {"valid": False, "reason": "trailing_garbage"}

        # For non-snapshot templates, check time window (robust to spaces/newlines)
        if template != "top_holders_snapshot":
            time_window_pattern = re.compile(
                r"block_timestamp\s+between\s+.*?@from_ts.*?\s+and\s+.*?@to_ts",
                re.IGNORECASE | re.DOTALL,
            )
            if not time_window_pattern.search(sql_lower):
                return {"valid": False, "reason": "missing_time_window"}

        return {"valid": True}

    def _check_freshness(self) -> Dict[str, Any]:
        """Check data freshness via freshness endpoint."""
        try:
            # Call local freshness endpoint
            result = self.freshness("eth")
            if result.get("data_as_of"):
                # Parse timestamp
                if isinstance(result["data_as_of"], str):
                    data_as_of = datetime.fromisoformat(
                        result["data_as_of"].replace("Z", "+00:00")
                    )
                else:
                    data_as_of = result["data_as_of"]

                # Check lag
                now = datetime.now(timezone.utc)
                lag_seconds = (now - data_as_of).total_seconds()
                freshness_slo = int(os.getenv("FRESHNESS_SLO", "600"))

                return {
                    "data_as_of": data_as_of,
                    "lag": lag_seconds > freshness_slo,
                    "lag_seconds": lag_seconds,
                }
        except Exception as e:
            log_json(stage="bq.check_freshness", error=str(e))

        return {"lag": True}

    def _prepare_query_params(
        self, params: Dict[str, Any], template: str
    ) -> List[bigquery.ScalarQueryParameter]:
        """Prepare BigQuery query parameters."""
        query_params = []

        # Address parameter
        if "address" in params:
            query_params.append(
                bigquery.ScalarQueryParameter("address", "STRING", params["address"])
            )

        # Time parameters
        if "from_ts" in params:
            query_params.append(
                bigquery.ScalarQueryParameter(
                    "from_ts",
                    "TIMESTAMP",
                    datetime.fromtimestamp(params["from_ts"], tz=timezone.utc),
                )
            )

        if "to_ts" in params:
            query_params.append(
                bigquery.ScalarQueryParameter(
                    "to_ts",
                    "TIMESTAMP",
                    datetime.fromtimestamp(params["to_ts"], tz=timezone.utc),
                )
            )

        # Optional parameters
        if "window_minutes" in params:
            query_params.append(
                bigquery.ScalarQueryParameter(
                    "window_minutes", "INT64", params["window_minutes"]
                )
            )

        if "top_n" in params:
            query_params.append(
                bigquery.ScalarQueryParameter("top_n", "INT64", params["top_n"])
            )

        return query_params

    def _generate_cache_key(
        self, template: str, params: Dict[str, Any], sql: str
    ) -> str:
        """Generate stable cache key."""
        # Use template, address, window (or time range), and SQL hash
        key_parts = [
            "bq:tpl",
            template,
            params.get("address", ""),
            str(
                params.get(
                    "window_minutes",
                    f"{params.get('from_ts', 0)}-{params.get('to_ts', 0)}",
                )
            ),
            hashlib.md5(sql.encode()).hexdigest()[:8],
        ]
        return ":".join(key_parts)

    def _dry_run_with_params(
        self,
        sql: str,
        query_params: List,
        template: Optional[str] = None,
        chain: Optional[str] = None,
        source: str = "template",
    ) -> int:
        """Dry-run query with parameters."""
        tpl_label = _label_tpl(template)
        chain_label = _label_chain(chain)
        try:
            job_config = bigquery.QueryJobConfig(
                query_parameters=query_params, dry_run=True, use_query_cache=False
            )
            query_job = self.client._get_client().query(sql, job_config=job_config)
            bytes_scanned = query_job.total_bytes_processed or 0
            METRIC_BQ_QUERY_TOTAL.inc(
                labels={
                    "tpl": tpl_label,
                    "chain": chain_label,
                    "source": source,
                    "kind": "dry_run",
                }
            )
            return bytes_scanned
        except Exception as e:
            log_json(stage="bq.dry_run", error=str(e))
            METRIC_BQ_DRY_RUN_FAIL.inc(labels={"tpl": tpl_label, "chain": chain_label})
            raise

    def _execute_with_params(
        self,
        sql: str,
        query_params: List,
        max_bytes: int,
        template: Optional[str] = None,
        chain: Optional[str] = None,
        source: str = "template",
    ) -> List[Dict]:
        """Execute query with parameters and cost limit."""
        tpl_label = _label_tpl(template)
        chain_label = _label_chain(chain)
        job_config = bigquery.QueryJobConfig(
            query_parameters=query_params, maximum_bytes_billed=max_bytes
        )
        start = time.perf_counter()
        query_job = self.client._get_client().query(sql, job_config=job_config)
        results_iter = query_job.result()
        results = list(results_iter)
        elapsed = time.perf_counter() - start
        bytes_processed = getattr(query_job, "total_bytes_processed", 0) or 0

        METRIC_BQ_QUERY_TOTAL.inc(
            labels={
                "tpl": tpl_label,
                "chain": chain_label,
                "source": source,
                "kind": "query",
            }
        )
        METRIC_BQ_BYTES_SCANNED_TOTAL.inc(
            labels={"tpl": tpl_label, "chain": chain_label}, value=bytes_processed
        )
        METRIC_BQ_LAST_JOB_BYTES.set(
            bytes_processed, labels={"tpl": tpl_label, "chain": chain_label}
        )
        METRIC_BQ_QUERY_LATENCY.observe(
            elapsed, labels={"tpl": tpl_label, "chain": chain_label, "source": source}
        )

        # Convert to dicts
        rows = []
        for row in results:
            row_dict = {}
            for field in row.keys():
                value = row[field]
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                row_dict[field] = value
            rows.append(row_dict)

        return rows

    def _process_template_results(
        self, rows: List[Dict], template: str, params: Dict
    ) -> Dict:
        """Process template results into response format."""
        response = {"template": template, "address": params.get("address")}

        # Extract data_as_of from results
        data_as_of = None
        if rows:
            # Look for data_as_of field in first row
            if "data_as_of" in rows[0]:
                data_as_of = rows[0]["data_as_of"]

            # For single-row aggregates, return as object
            if len(rows) == 1 and template in [
                "active_addrs_window",
                "token_transfers_window",
            ]:
                response.update(rows[0])
            else:
                # Return as rows array
                response["rows"] = rows
        else:
            response["rows"] = []

        if data_as_of:
            response["data_as_of"] = data_as_of
        else:
            # Fallback to current time
            response["data_as_of"] = datetime.now(timezone.utc).isoformat()

        return response

    def query_light_features(
        self, chain: str, address: str, window_minutes: int = 60
    ) -> List[Dict]:
        """
        Query lightweight features from view/table using chain+address.
        Card D routes use this method.

        Args:
            chain: Blockchain name (e.g., "eth", "polygon")
            address: Contract or wallet address
            window_minutes: Time window in minutes

        Returns:
            List of feature rows or empty list
        """
        view = self.settings.onchain_view
        if not view:
            raise RuntimeError(
                "BQ_ONCHAIN_FEATURES_VIEW not configured. "
                "Set BQ_ONCHAIN_FEATURES_VIEW=<project.dataset.table_or_view>"
            )

        # Query using actual view columns
        sql = f"""
            SELECT
              as_of_ts,
              window_minutes,
              addr_active,
              growth_ratio,
              top10_share,
              self_loop_ratio
            FROM `{view}`
            WHERE chain = @chain 
              AND address = @address 
              AND window_minutes = @window
            ORDER BY as_of_ts DESC
            LIMIT 200
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("chain", "STRING", chain),
                bigquery.ScalarQueryParameter("address", "STRING", address),
                bigquery.ScalarQueryParameter("window", "INT64", window_minutes),
            ],
            maximum_bytes_billed=int(self.settings.max_scanned_gb * (1024**3)),
        )

        try:
            METRIC_BQ_MAX_BYTES.set(job_config.maximum_bytes_billed or 0)
            start = time.perf_counter()
            query_job = self.client._get_client().query(
                sql, job_config=job_config, location=self.settings.location
            )
            results = query_job.result(timeout=self.settings.timeout_s)
            elapsed = time.perf_counter() - start
            bytes_processed = getattr(query_job, "total_bytes_processed", 0) or 0

            # Convert to list of dicts
            rows = []
            for row in results:
                row_dict = {}
                for field in row.keys():
                    value = row[field]
                    if hasattr(value, "isoformat"):
                        value = value.isoformat()
                    row_dict[field] = value
                rows.append(row_dict)

            log_json(
                stage="bq.query_light_features",
                chain=chain,
                address=address,
                window_minutes=window_minutes,
                row_count=len(rows),
            )

            tpl_label = _label_tpl("light_view")
            chain_label = _label_chain(chain)
            METRIC_BQ_QUERY_TOTAL.inc(
                labels={
                    "tpl": tpl_label,
                    "chain": chain_label,
                    "source": "view",
                    "kind": "query",
                }
            )
            METRIC_BQ_BYTES_SCANNED_TOTAL.inc(
                labels={"tpl": tpl_label, "chain": chain_label}, value=bytes_processed
            )
            METRIC_BQ_LAST_JOB_BYTES.set(
                bytes_processed, labels={"tpl": tpl_label, "chain": chain_label}
            )
            METRIC_BQ_QUERY_LATENCY.observe(
                elapsed,
                labels={"tpl": tpl_label, "chain": chain_label, "source": "view"},
            )

            return rows

        except Exception as e:
            log_json(
                stage="bq.query_light_features",
                error=str(e),
                chain=chain,
                address=address,
            )
            return []
