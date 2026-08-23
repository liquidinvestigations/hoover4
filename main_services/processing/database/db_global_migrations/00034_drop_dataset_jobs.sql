-- Drop the per-dataset job table. The operations log replaces it.
--
-- `dataset_jobs` was a second progress mechanism beside `operations`, with its own state
-- names, its own lock and its own polling path, so a dataset page and the operations log
-- could describe the same run differently. Everything that wrote it now writes an
-- operations row, which is the permanent record and the lock at once.
--
-- NOTE: keep semicolons out of comment strings. The migration runner splits on that
-- character without parsing quotes or comments.
DROP TABLE IF EXISTS dataset_jobs;
