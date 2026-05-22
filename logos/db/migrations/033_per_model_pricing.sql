DROP VIEW IF EXISTS budget_usage CASCADE;

ALTER TABLE token_prices
    ADD COLUMN IF NOT EXISTS model_id INTEGER REFERENCES models(id) ON DELETE CASCADE;

ALTER TABLE token_prices
    ALTER COLUMN price_per_k_token TYPE BIGINT USING ROUND(price_per_k_token)::BIGINT;

CREATE VIEW budget_usage AS
SELECT
    le.api_key_id,
    DATE_TRUNC('month', le.timestamp_request)::DATE AS month,
    COALESCE(SUM(
        CASE WHEN tp.price_per_k_token IS NOT NULL
             THEN (ut.token_count::BIGINT * tp.price_per_k_token / 1000)::BIGINT
             ELSE 0
        END
    ), 0) AS cost_micro_cents
FROM log_entry le
JOIN usage_tokens ut ON ut.log_entry_id = le.id
LEFT JOIN LATERAL (
    SELECT price_per_k_token
    FROM token_prices
    WHERE type_id = ut.type_id
      AND (model_id = le.model_id OR model_id IS NULL)
      AND valid_from <= le.timestamp_request
    ORDER BY (model_id = le.model_id) DESC NULLS LAST,
             valid_from DESC
    LIMIT 1
) tp ON true
WHERE le.api_key_id IS NOT NULL
GROUP BY le.api_key_id, DATE_TRUNC('month', le.timestamp_request)::DATE;
