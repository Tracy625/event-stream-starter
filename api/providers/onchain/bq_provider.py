"""BigQuery onchain data provider with template support."""
import os
from typing import Dict, List, Any, Optional
from pathlib import Path
from api.clients.bq_client import BQClient
from api.utils.logging import log_json


class BQProvider:
    """Onchain data provider using BigQuery."""
    
    def __init__(self):
        self.client = BQClient()
        self.templates_dir = Path(__file__).parent.parent.parent.parent / "templates" / "sql"
        
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
            return {"degrade": True, "reason": "bq_off"}
            
        try:
            # Load template
            template_path = self.templates_dir / f"{name}.sql"
            if template_path.exists():
                with open(template_path, 'r') as f:
                    sql_template = f.read()
            else:
                # Fallback to inline templates for known queries
                sql_template = self._get_inline_template(name)
                if not sql_template:
                    log_json(stage="bq_provider.run_template", error="template_not_found", template=name)
                    return {"degrade": True, "reason": "template_not_found", "template": name}
            
            # Simple template substitution (using format for now, can upgrade to jinja2 later)
            try:
                sql = sql_template.format(**kwargs)
            except KeyError as e:
                log_json(stage="bq_provider.run_template", error="template_param_missing", template=name, missing_param=str(e))
                return {"degrade": True, "reason": "template_param_error", "template": name}
            
            log_json(stage="bq_provider.run_template", template=name, params=kwargs)
            
            # First do dry-run check
            bytes_scanned = self.client.dry_run(sql)
            if bytes_scanned < 0:
                return {"degrade": True, "reason": "dry_run_failed", "template": name}
                
            # Check cost guard
            estimated_gb = bytes_scanned / 1e9
            if estimated_gb > self.client.max_scanned_gb:
                log_json(
                    stage="bq_provider.run_template",
                    cost_guard_hit=True,
                    template=name,
                    bq_bytes_scanned=bytes_scanned,
                    estimated_gb=round(estimated_gb, 3)
                )
                return {
                    "degrade": True,
                    "reason": "cost_guard",
                    "bq_bytes_scanned": bytes_scanned,
                    "template": name
                }
            
            # Execute query
            results = list(self.client.query(sql))
            
            # Convert results to dict/list format
            if not results:
                return {"degrade": True, "reason": "no_data", "template": name}
                
            # If single row with specific fields, return as dict
            if len(results) == 1 and name in ["freshness_eth", "healthz_probe"]:
                row = results[0]
                response = {}
                for field in row.keys():
                    value = row[field]
                    # Convert datetime objects to ISO format
                    if hasattr(value, 'isoformat'):
                        value = value.isoformat()
                    response[field] = value
                    
                log_json(
                    stage="bq_provider.run_template",
                    success=True,
                    template=name,
                    bq_bytes_scanned=bytes_scanned
                )
                return response
            
            # Otherwise return as list of dicts
            response = []
            for row in results:
                row_dict = {}
                for field in row.keys():
                    value = row[field]
                    if hasattr(value, 'isoformat'):
                        value = value.isoformat()
                    row_dict[field] = value
                response.append(row_dict)
                
            log_json(
                stage="bq_provider.run_template",
                success=True,
                template=name,
                bq_bytes_scanned=bytes_scanned,
                rows_returned=len(response)
            )
            return response
            
        except Exception as e:
            log_json(
                stage="bq_provider.run_template",
                error=str(e),
                template=name,
                degrade=True
            )
            return {"degrade": True, "reason": "provider_error", "template": name}
    
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
            """
        }
        
        template = templates.get(name)
        if template:
            # Inject default dataset if not provided
            dataset = os.getenv("BQ_DATASET_RO", "bigquery-public-data.crypto_ethereum")
            return template.replace("{dataset}", dataset)
            
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
        template_map = {
            "eth": "freshness_eth",
            "ethereum": "freshness_eth"
        }
        
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
                        log_json(
                            stage="bq_provider.freshness",
                            success=True,
                            chain=chain,
                            latest_block=result.get("latest_block"),
                            data_as_of=result.get("data_as_of")
                        )
                        
                return result
                
            return {"degrade": True, "reason": "unexpected_result", "chain": chain}
            
        except Exception as e:
            log_json(stage="bq_provider.freshness", error=str(e), chain=chain, degrade=True)
            return {"degrade": True, "reason": "freshness_error", "chain": chain}