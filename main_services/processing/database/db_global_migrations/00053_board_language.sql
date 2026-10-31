-- The language of each investigation board.
--
-- The website writes the agent language of the owner when it creates the board. An explore
-- uses the saved agent language of the owner, then the saved interface language, then this
-- value. An empty value means English.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE boards
    ADD COLUMN IF NOT EXISTS language LowCardinality(String) DEFAULT ''
    COMMENT 'The agent language code of the owner at creation, used when the owner has saved none'
    AFTER internet_tools
