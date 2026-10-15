-- The notification tables belong solely to the notification feature, so a
-- full wipe is a safe, complete cleanup (also removes rows published with
-- auto-generated ids during a test method).
DELETE FROM notification_reads;
DELETE FROM notification_recipients;
DELETE FROM notifications;
