-- Local UI demo data only. Safe to run repeatedly.
-- Adds three recent requests for each demo provider/model pair so that
-- p50, p95, and p100 produce visibly different values.

INSERT INTO token_types (name, description)
VALUES ('completion_tokens', 'Created by provider performance demo seed')
ON CONFLICT (name) DO NOTHING;

DELETE FROM log_entry
WHERE environment = 'provider-performance-demo';

WITH demo_data (
    provider_name,
    model_name,
    request_id,
    request_age,
    ttft_ms,
    tpot_ms,
    was_cold_start,
    completion_tokens
) AS (
    VALUES
        (
            'Anthropic Fable 5',
            'fable-5',
            'demo-provider-performance-anthropic-1',
            INTERVAL '30 minutes',
            480,
            180,
            false,
            21::BIGINT
        ),
        (
            'Anthropic Fable 5',
            'fable-5',
            'demo-provider-performance-anthropic-2',
            INTERVAL '25 minutes',
            600,
            220,
            false,
            21::BIGINT
        ),
        (
            'Anthropic Fable 5',
            'fable-5',
            'demo-provider-performance-anthropic-3',
            INTERVAL '20 minutes',
            900,
            300,
            true,
            21::BIGINT
        ),
        (
            'OpenAI Sol 5.6',
            'gpt-5.6-mini',
            'demo-provider-performance-openai-1',
            INTERVAL '15 minutes',
            250,
            90,
            false,
            31::BIGINT
        ),
        (
            'OpenAI Sol 5.6',
            'gpt-5.6-mini',
            'demo-provider-performance-openai-2',
            INTERVAL '10 minutes',
            350,
            100,
            true,
            31::BIGINT
        ),
        (
            'OpenAI Sol 5.6',
            'gpt-5.6-mini',
            'demo-provider-performance-openai-3',
            INTERVAL '5 minutes',
            650,
            160,
            true,
            31::BIGINT
        )
), resolved AS (
    SELECT d.*,
           p.id AS provider_id,
           m.id AS model_id,
           NOW() - d.request_age AS timestamp_request,
           NOW() - d.request_age + INTERVAL '100 milliseconds' AS timestamp_forwarding,
           NOW() - d.request_age + d.ttft_ms * INTERVAL '1 millisecond' AS time_at_first_token,
           NOW() - d.request_age
               + (d.ttft_ms + d.tpot_ms * GREATEST(d.completion_tokens - 1, 1))
                   * INTERVAL '1 millisecond' AS timestamp_response
    FROM demo_data d
    JOIN providers p ON p.name = d.provider_name
    JOIN model_provider mp ON mp.provider_id = p.id
    JOIN models m ON m.id = mp.model_id AND m.name = d.model_name
), inserted AS (
    INSERT INTO log_entry (
        request_id,
        provider_id,
        model_id,
        result_status,
        timestamp_request,
        timestamp_forwarding,
        time_at_first_token,
        timestamp_response,
        was_cold_start,
        environment
    )
    SELECT
        request_id,
        provider_id,
        model_id,
        'success',
        timestamp_request,
        timestamp_forwarding,
        time_at_first_token,
        timestamp_response,
        was_cold_start,
        'provider-performance-demo'
    FROM resolved
    RETURNING id, request_id
)
INSERT INTO usage_tokens (type_id, log_entry_id, token_count)
SELECT tt.id, i.id, r.completion_tokens
FROM inserted i
JOIN resolved r ON r.request_id = i.request_id
JOIN token_types tt ON tt.name = 'completion_tokens';

SELECT request_id, environment
FROM log_entry
WHERE environment = 'provider-performance-demo'
ORDER BY request_id;
