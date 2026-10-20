-- Each table sheet records how its reader read row 1.
-- header_state is established, ambiguous or legacy. A row written before this migration is legacy.
-- header_basis is format, heuristic or missing. A legacy row has the basis missing.
-- header_candidates holds the header row_id of each plausible reading. The value 0 is the reading with no header row.
-- header_row stays the display choice of the website grid.
ALTER TABLE table_sheets ADD COLUMN IF NOT EXISTS header_state LowCardinality(String) DEFAULT 'legacy' COMMENT 'established, ambiguous or legacy';
ALTER TABLE table_sheets ADD COLUMN IF NOT EXISTS header_basis LowCardinality(String) DEFAULT 'missing' COMMENT 'format, heuristic or missing';
ALTER TABLE table_sheets ADD COLUMN IF NOT EXISTS header_candidates Array(UInt64) DEFAULT [] COMMENT 'Header row_id of each plausible reading, 0 for no header row';
