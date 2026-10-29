-- The uploader flag of a group membership.
--
-- A user may upload into a collection only through a membership with is_uploader = 1 whose
-- group holds a live collection_group_permissions row for that collection. A public
-- collection and the administrator flag of a user give no upload permission.
--
-- The website is the only writer of this table. It reads the stored row and writes the
-- complete row under a lock for the user, so a change of one flag keeps the other flag. A
-- membership that the login proxy sync creates starts with the flag clear. The sync keeps
-- every column of an existing membership.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE user_group_membership
    ADD COLUMN IF NOT EXISTS is_uploader UInt8 DEFAULT 0
    COMMENT 'The member may upload into the upload dataset of each collection that the group can read'
