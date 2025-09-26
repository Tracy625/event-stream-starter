-- active_addrs_window.sql
-- Query active addresses in a time window for a given contract
-- Parameters: @address, @from_ts, @to_ts, @window_minutes
-- Returns: transaction count, active address count, data freshness timestamp

SELECT
  COUNT(1) AS tx_count,
  COUNT(DISTINCT from_address) AS active_addr_count,
  MAX(block_timestamp) AS data_as_of
FROM `{{ BQ_DATASET_RO }}.transactions`
WHERE to_address = @address
  AND block_timestamp BETWEEN @from_ts AND @to_ts
LIMIT 50000;
