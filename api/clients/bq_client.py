"""BigQuery client with dry-run guard and timeout support."""

import os
import random
import time
from datetime import datetime
from typing import Any, Dict, Iterator, Optional

from api.utils.logging import log_json


class BQClient:
    """BigQuery client with cost guards and graceful degradation."""

    def __init__(self):
        self.project = os.getenv("GCP_PROJECT", "")
        self.location = os.getenv("BQ_LOCATION", "US")
        self.dataset_ro = os.getenv(
            "BQ_DATASET_RO", "bigquery-public-data.crypto_ethereum"
        )
        self.timeout_s = int(os.getenv("BQ_TIMEOUT_S", "60"))
        self.max_scanned_gb = float(os.getenv("BQ_MAX_SCANNED_GB", "5"))
        self.backend = os.getenv("ONCHAIN_BACKEND", "bq")
        self._client = None

    def _get_client(self):
        """Lazy load BigQuery client."""
        if self._client is None:
            # Lazy import to avoid breaking environments without google-cloud-bigquery
            try:
                from google.cloud import bigquery

                self._client = bigquery.Client(
                    project=self.project, location=self.location
                )
            except ImportError:
                log_json(
                    stage="bq.import_error", error="google-cloud-bigquery not installed"
                )
                return None
            except Exception as e:
                log_json(stage="bq.client_error", error=str(e))
                return None
        return self._client

    def dry_run(self, sql: str, params: Optional[Dict] = None) -> int:
        """
        Execute a dry-run query to estimate bytes scanned.

        Returns:
            bytes_scanned (int): Estimated bytes that would be scanned, or -1 on error
        """
        if self.backend == "off":
            log_json(stage="bq.dry_run", backend_off=True)
            return 0

        client = self._get_client()
        if not client:
            log_json(stage="bq.dry_run", degrade=True, reason="client_unavailable")
            return -1

        try:
            from google.cloud.bigquery import QueryJobConfig

            # Calculate max bytes from GB
            max_bytes = int(float(os.getenv("BQ_MAX_SCANNED_GB", "5")) * (1024**3))

            config_kwargs = {"dry_run": True, "use_query_cache": False}

            if params:
                config_kwargs["query_parameters"] = self._build_query_params(params)

            job_config = QueryJobConfig(**config_kwargs)

            query_job = client.query(sql, job_config=job_config)
            bytes_scanned = query_job.total_bytes_processed or 0

            log_json(
                stage="bq.dry_run",
                dry_run_pass=True,
                bq_bytes_scanned=bytes_scanned,
                estimated_gb=round(bytes_scanned / 1e9, 3),
            )
            return bytes_scanned

        except Exception as e:
            log_json(stage="bq.dry_run", error=str(e), degrade=True)
            return -1

    def query(
        self, sql: str, params: Optional[Dict] = None, timeout_s: Optional[int] = None
    ) -> Iterator[Any]:
        """
        Execute a query with timeout and retry logic.

        Returns:
            Iterator of Row objects, or empty iterator on error
        """
        if self.backend == "off":
            log_json(stage="bq.query", backend_off=True, degrade=True)
            return iter([])

        # First do dry-run to check cost
        bytes_scanned = self.dry_run(sql, params)
        if bytes_scanned < 0:
            log_json(stage="bq.query", degrade=True, reason="dry_run_failed")
            return iter([])

        # Check cost guard
        estimated_gb = bytes_scanned / 1e9
        if estimated_gb > self.max_scanned_gb:
            log_json(
                stage="bq.query",
                cost_guard_hit=True,
                degrade=True,
                reason="cost_guard",
                bq_bytes_scanned=bytes_scanned,
                estimated_gb=round(estimated_gb, 3),
                max_allowed_gb=self.max_scanned_gb,
            )
            return iter([])

        client = self._get_client()
        if not client:
            log_json(stage="bq.query", degrade=True, reason="client_unavailable")
            return iter([])

        timeout = timeout_s or self.timeout_s
        max_retries = 3

        for attempt in range(max_retries):
            try:
                from google.cloud.bigquery import QueryJobConfig

                # Calculate max bytes from GB
                max_bytes = int(float(os.getenv("BQ_MAX_SCANNED_GB", "5")) * (1024**3))

                config_kwargs = {
                    "use_query_cache": True,
                    "maximum_bytes_billed": max_bytes,
                }

                if params:
                    config_kwargs["query_parameters"] = self._build_query_params(params)

                job_config = QueryJobConfig(**config_kwargs)

                query_job = client.query(sql, job_config=job_config, timeout=timeout)
                results = query_job.result(timeout=timeout)

                log_json(
                    stage="bq.query",
                    success=True,
                    bq_bytes_scanned=query_job.total_bytes_processed or 0,
                    maximum_bytes_billed=max_bytes,
                    rows_returned=query_job.num_dml_affected_rows or 0,
                    attempt=attempt + 1,
                )

                return results

            except Exception as e:
                error_str = str(e)
                is_transient = any(
                    x in error_str.lower()
                    for x in ["timeout", "deadline", "unavailable", "rate"]
                )

                if is_transient and attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    wait_time = (2**attempt) + random.uniform(0, 1)
                    log_json(
                        stage="bq.query",
                        retry=True,
                        attempt=attempt + 1,
                        wait_s=round(wait_time, 2),
                        error=error_str,
                    )
                    time.sleep(wait_time)
                    continue

                log_json(
                    stage="bq.query",
                    degrade=True,
                    reason="query_error",
                    error=error_str,
                    attempt=attempt + 1,
                )
                return iter([])

        return iter([])

    def probe_connectivity(self) -> Dict:
        """
        Lightweight connectivity probe using dry-run only.

        Returns:
            {probe: 1, dry_run_pass: bool, bq_bytes_scanned: int, cost_guard_hit: bool}
        """
        if self.backend == "off":
            return {
                "probe": 1,
                "dry_run_pass": False,
                "bq_bytes_scanned": 0,
                "cost_guard_hit": False,
            }

        # Use a minimal query for dry-run
        sql = f"SELECT 1 AS probe FROM `{self.dataset_ro}.blocks` LIMIT 1"

        bytes_scanned = self.dry_run(sql)

        if bytes_scanned < 0:
            return {
                "probe": 1,
                "dry_run_pass": False,
                "bq_bytes_scanned": 0,
                "cost_guard_hit": False,
            }

        # Check if cost guard would be hit
        estimated_gb = bytes_scanned / 1e9
        cost_guard_hit = estimated_gb > self.max_scanned_gb

        log_json(
            stage="bq.probe_connectivity",
            dry_run_pass=True,
            bq_bytes_scanned=bytes_scanned,
            cost_guard_hit=cost_guard_hit,
        )

        return {
            "probe": 1,
            "dry_run_pass": True,
            "bq_bytes_scanned": bytes_scanned,
            "cost_guard_hit": cost_guard_hit,
        }

    def freshness(self, dataset: str, chain: str) -> Dict:
        """
        Get freshness info for a specific chain.

        Returns:
            {latest_block: int, data_as_of: str} or degraded response
        """
        if self.backend == "off":
            return {"degrade": True, "reason": "bq_off"}

        # Build query based on chain
        if chain == "eth":
            sql = f"""
            SELECT
              number AS latest_block,
              timestamp AS data_as_of
            FROM `{self.dataset_ro}.blocks`
            ORDER BY number DESC
            LIMIT 1
            """
        else:
            log_json(stage="bq.freshness", unsupported_chain=chain)
            return {"degrade": True, "reason": "unsupported_chain", "chain": chain}

        try:
            results = list(self.query(sql))
            if not results:
                return {"degrade": True, "reason": "no_data"}

            row = results[0]
            data_as_of = (
                row.data_as_of.isoformat()
                if hasattr(row.data_as_of, "isoformat")
                else str(row.data_as_of)
            )

            response = {"latest_block": row.latest_block, "data_as_of": data_as_of}

            log_json(
                stage="bq.freshness",
                success=True,
                chain=chain,
                latest_block=row.latest_block,
                data_as_of=data_as_of,
            )

            return response

        except Exception as e:
            log_json(stage="bq.freshness", error=str(e), degrade=True)
            return {"degrade": True, "reason": "query_error"}

    def _build_query_params(self, params: Dict) -> list:
        """Build query parameters for parameterized queries."""
        if not params:
            return []

        # Lazy import
        from google.cloud.bigquery import ScalarQueryParameter

        query_params = []
        for key, value in params.items():
            param_type = "STRING"
            if isinstance(value, int):
                param_type = "INT64"
            elif isinstance(value, float):
                param_type = "FLOAT64"
            elif isinstance(value, bool):
                param_type = "BOOL"

            query_params.append(ScalarQueryParameter(key, param_type, value))

        return query_params
