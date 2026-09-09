-- Billing target for the price-close interleaving regression: a team and an
-- active key whose budget history the test reads through
-- LogEntryBillingRepository.findKeyBudgetHistory.

INSERT INTO teams (id, name) VALUES (2003, 'billing-team');

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active)
VALUES (5301, 'billing-key-1', 'billing key', 'developer', NULL, 2003, true);

-- A third open price row for the same provider (6101) and model (5101) as
-- the metrics seed's rows 92101/92102, but a token type of its own: the
-- close must stamp prompt, completion, and reasoning rows with one identical
-- valid_to boundary.
INSERT INTO token_types (id, name) VALUES (9103, 'completion_reasoning_tokens');

INSERT INTO token_prices (id, type_id, model_id, provider_id, valid_from, price_per_k_token)
VALUES (92106, 9103, 5101, 6101, NOW() - INTERVAL '1 year', 3000);
