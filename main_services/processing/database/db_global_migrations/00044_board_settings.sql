-- Investigation boards for every user, with the internet tools as a board setting.
--
-- The website writes a new version of the board row when the owner changes a setting. The
-- collections stay as they were at creation. The explore budget and the step count of an
-- explore are computed by the worker from the events, so the two budget columns keep only
-- the base values that the website writes.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE boards
    ADD COLUMN IF NOT EXISTS internet_tools UInt8 DEFAULT 1
    COMMENT 'Whether explores may use the internet tools, when the deployment has them'
    AFTER explore_step_budget;

ALTER TABLE boards
    COMMENT COLUMN owner 'The user who created the board. Only the owner can read it';
