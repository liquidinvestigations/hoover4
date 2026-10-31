-- Each table parse writes a generation, a number that is unique for the hash in the collection.
-- The cells, sheets and columns of a parse carry its generation, and the generation is in the sort key, so a new parse never replaces the rows of the published one.
-- The table_documents row of a dataset names the generation that its readers read. It is the last write of a parse.
-- Rows written before this migration have generation 0, which their manifests also name.
-- A column in a new sort key cannot have a default expression, so the three generation columns take the UInt32 default 0.
-- A generation that no manifest names and that is older than a named one is removed by the orphan sweep.
ALTER TABLE table_cells ADD COLUMN IF NOT EXISTS generation UInt32 COMMENT 'Parse generation, named by table_documents.generation', MODIFY ORDER BY (file_hash, sheet_id, column_id, row_id, generation);
ALTER TABLE table_sheets ADD COLUMN IF NOT EXISTS generation UInt32 COMMENT 'Parse generation, named by table_documents.generation', MODIFY ORDER BY (collection_dataset, hash, sheet_id, generation);
ALTER TABLE table_columns ADD COLUMN IF NOT EXISTS generation UInt32 COMMENT 'Parse generation, named by table_documents.generation', MODIFY ORDER BY (collection_dataset, hash, sheet_id, column_id, generation);
-- status is parsing, ok, failed or empty. An empty row is a parse that found no table, and it hides an earlier table of the hash.
ALTER TABLE table_documents ADD COLUMN IF NOT EXISTS generation UInt32 DEFAULT 0 COMMENT 'The generation of table_cells, table_sheets and table_columns that this dataset reads'
