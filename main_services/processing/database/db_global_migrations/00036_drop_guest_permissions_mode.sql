-- Remove the leftover guest_permissions_mode server setting.
--
-- The guest identity path is gone, and this key has no reader. server_settings is a
-- ReplacingMergeTree keyed on updated_at with is_deleted as the tombstone, and
-- every reader filters FINAL WHERE is_deleted = 0, so this row hides the key from
-- the admin page at once.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
INSERT INTO server_settings (key, value, is_deleted) VALUES ('guest_permissions_mode', '', 1);
