-- A group holds AI chats and investigation boards only when ai_enabled is 1.
--
-- The website lists only these groups when a person creates a chat or a board, and refuses
-- a create request for another group (website/backend/src/auth/item_access.rs). An
-- administrator sets the flag on the admin page of the group. The flag goes off only for a
-- group that owns no chat and no board.
--
-- The groups user and admin start with the flag set. The first INSERT writes a newer row
-- for each stored live row of the two groups and keeps its full name. The second INSERT
-- adds a row for a group of the two that has no live row.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE user_groups
    ADD COLUMN IF NOT EXISTS ai_enabled UInt8 DEFAULT 0
    COMMENT '1 when the group can hold AI chats and investigation boards';

INSERT INTO user_groups (groupname, fullname, created_at, updated_at, is_deleted, ai_enabled)
SELECT groupname, fullname, created_at, now(), 0, 1
FROM user_groups FINAL
WHERE groupname IN ('user', 'admin') AND is_deleted = 0;

INSERT INTO user_groups (groupname, fullname, ai_enabled)
SELECT name, name, 1
FROM (SELECT arrayJoin(['user', 'admin']) AS name)
WHERE name NOT IN (SELECT groupname FROM user_groups FINAL WHERE is_deleted = 0);
