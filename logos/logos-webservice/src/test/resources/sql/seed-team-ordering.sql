-- Case-pair fixture for the team listing sort test: the names are equal
-- ignoring case, so the id tiebreak decides between them, and the INSERT
-- order (2004 before 2003) is deliberately opposite to the id order so a
-- stable sort without the id tiebreak would keep the physical row order and
-- fail the assertion. DELETE first so a re-run never hits a PK conflict.
DELETE FROM team_members
WHERE team_id IN (2003, 2004);
DELETE FROM teams WHERE id IN (2003, 2004);
INSERT INTO teams (id, name) VALUES (2004, 'Beta-Team');
INSERT INTO teams (id, name) VALUES (2003, 'beta-team');
