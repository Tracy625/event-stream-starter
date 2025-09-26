-- token_transfers_window.sql
-- Query token transfer statistics in a time window
-- Parameters: @address, @from_ts, @to_ts, @window_minutes
-- Returns: transfer count, sender/receiver counts, data freshness timestamp

SELECT
  COUNT(1) AS transfer_count,
  COUNT(DISTINCT from_address) AS sender_count,
  COUNT(DISTINCT to_address) AS receiver_count,
  MAX(block_timestamp) AS data_as_of
FROM `{{ BQ_DATASET_RO }}.token_transfers`
WHERE token_address = @address
  AND block_timestamp BETWEEN TIMESTAMP_SECONDS(@from_ts) AND TIMESTAMP_SECONDS(@to_ts)
LIMIT 50000;