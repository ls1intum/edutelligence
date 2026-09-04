-- Removes only rows created by seed-provider-performance-demo.sql.

DELETE FROM log_entry
WHERE environment = 'provider-performance-demo';

DELETE FROM token_types tt
WHERE tt.name = 'completion_tokens'
  AND tt.description = 'Created by provider performance demo seed'
  AND NOT EXISTS (
      SELECT 1
      FROM usage_tokens ut
      WHERE ut.type_id = tt.id
  );

SELECT COUNT(*) AS remaining_demo_requests
FROM log_entry
WHERE environment = 'provider-performance-demo';
