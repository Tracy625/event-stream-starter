-- top_holders_snapshot.sql
-- Query top token holders from latest balance snapshot
-- Parameters: @address, @top_n (optional, default 20)
-- Returns: holder address, balance, total balance, percentage, data freshness timestamp

-- Path 1: Use latest balance snapshot (preferred if exists)
SELECT 
  holder,
  balance,
  SUM(balance) OVER () AS total_balance,
  SAFE_DIVIDE(balance, SUM(balance) OVER ()) AS pct,
  MAX(updated_at) OVER () AS data_as_of
FROM `{{ BQ_DATASET_RO }}.erc20_balances_latest`
WHERE token_address = @address
QUALIFY ROW_NUMBER() OVER (ORDER BY balance DESC) <= COALESCE(@top_n, 20)
LIMIT 1000;

-- Path 2: Approximate from transfers (fallback when snapshot unavailable)
-- Provider must mark as approximate=true when using this path
-- WITH recent_transfers AS (
--   SELECT 
--     to_address AS holder,
--     SUM(CAST(value AS NUMERIC)) AS net_balance,
--     MAX(block_timestamp) AS last_activity
--   FROM `{{ BQ_DATASET_RO }}.token_transfers`
--   WHERE token_address = @address
--     AND block_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
--   GROUP BY holder
-- )
-- SELECT 
--   holder,
--   net_balance AS balance,
--   SUM(net_balance) OVER () AS total_balance,
--   SAFE_DIVIDE(net_balance, SUM(net_balance) OVER ()) AS pct,
--   MAX(last_activity) OVER () AS data_as_of
-- FROM recent_transfers
-- WHERE net_balance > 0
-- QUALIFY ROW_NUMBER() OVER (ORDER BY net_balance DESC) <= COALESCE(@top_n, 20)
-- LIMIT 1000;
