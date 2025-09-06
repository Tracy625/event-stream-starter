-- Freshness probe for Ethereum blockchain
-- Returns the latest block number and timestamp
-- Designed to be partition-friendly with minimal scan

SELECT
  number AS latest_block,
  timestamp AS data_as_of
FROM `bigquery-public-data.crypto_ethereum.blocks`
ORDER BY number DESC
LIMIT 1