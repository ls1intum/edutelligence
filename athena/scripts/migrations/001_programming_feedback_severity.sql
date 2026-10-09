-- Apply once to each existing database containing programming_feedbacks,
-- before starting the updated services. Compatible with PostgreSQL and SQLite.
-- New databases receive this column through SQLAlchemy create_all.
ALTER TABLE programming_feedbacks
ADD COLUMN severity VARCHAR(6)
CONSTRAINT ck_programming_feedback_severity CHECK (severity IN ('low', 'medium', 'high'));
