-- Local UI demo data only. Safe to run repeatedly.
-- Adds one recent request for each demo provider/model pair.

INSERT INTO token_types (name, description)
VALUES ('completion_tokens', 'Created by provider performance demo seed')
ON CONFLICT (name) DO NOTHING;

DELETE FROM log_entry
WHERE environment = 'provider-performance-demo';

WITH demo_data (
    provider_name,
    model_name,
    request_id,
    timestamp_request,
    timestamp_forwarding,
    time_at_first_token,
    timestamp_response,
    was_cold_start,
    completion_tokens
) AS (
    VALUES
        (
            'Anthropic Fable 5',
            'fable-5',
            'demo-provider-performance-anthropic',
            NOW() - INTERVAL '20 minutes',
            NOW() - INTERVAL '19 minutes 59.8 seconds',
            NOW() - INTERVAL '19 minutes 59.4 seconds',
            NOW() - INTERVAL '19 minutes 55 seconds',
            false,
            21::BIGINT
        ),
        (
            'OpenAI Sol 5.6',
            'gpt-5.6-mini',
            'demo-provider-performance-openai',
            NOW() - INTERVAL '10 minutes',
            NOW() - INTERVAL '9 minutes 59.9 seconds',
            NOW() - INTERVAL '9 minutes 59.65 seconds',
            NOW() - INTERVAL '9 minutes 56.65 seconds',
            true,
            31::BIGINT
        )
), resolved AS (
    SELECT d.*, p.id AS provider_id, m.id AS model_id
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
