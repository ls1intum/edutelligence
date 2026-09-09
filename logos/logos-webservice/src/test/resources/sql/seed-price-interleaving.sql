-- Billing target for the price-close interleaving regression: a team and an
-- active key whose budget history the test reads through
-- LogEntryBillingRepository.findKeyBudgetHistory.

INSERT INTO teams (id, name) VALUES (2003, 'billing-team');

INSERT INTO api_keys (id, key_value, name, key_type, user_id, team_id, is_active)
VALUES (5301, 'billing-key-1', 'billing key', 'developer', NULL, 2003, true);
