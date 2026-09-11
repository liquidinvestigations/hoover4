-- The capture writes this table when an operation or a pipeline workflow fails.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
ALTER TABLE operation_failures
    MODIFY COMMENT 'One row per node of an operation failure tree';
